from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_teacher_authority import validate_teacher_input_document
from .photoreal_teacher_runner import PhotorealTeacherRunnerError
from .photoreal_teacher_semantic_alignment import (
    RECEIPT_FORMAT as SEMANTIC_ALIGNMENT_FORMAT,
    RECEIPT_VERSION as SEMANTIC_ALIGNMENT_VERSION,
)

REVIEW_MANIFEST_FORMAT = "bodyrig-photoreal-appearance-epoch-visual-review-manifest"
REVIEW_MANIFEST_VERSION = 1
HANDOFF_FORMAT = "bodyrig-photoreal-p1-heldout-pairing-handoff"
HANDOFF_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p1-heldout-pairing"
RECEIPT_VERSION = 1

CRITERION_ALLOWED_SEMANTIC_LABELS = {
    "face-front": ("front",),
    "face-three-quarter": ("front-left-three-quarter", "front-right-three-quarter"),
    "face-profile": ("left-profile", "right-profile"),
    "full-body-front": ("front",),
    "full-body-three-quarter": ("front-left-three-quarter", "front-right-three-quarter"),
    "full-body-profile": ("left-profile", "right-profile"),
    "full-body-rear": ("rear",),
}


class PhotorealP1HeldoutPairingError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP1HeldoutPairingError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP1HeldoutPairingError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP1HeldoutPairingError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP1HeldoutPairingError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP1HeldoutPairingError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP1HeldoutPairingError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP1HeldoutPairingError(f"{label} format/version mismatch")


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP1HeldoutPairingError("pairing artifact cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealP1HeldoutPairingError(f"required file is missing or not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_ref(source_key: str) -> str:
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:20]


def _safe_review_path(root: Path, relative: str) -> Path:
    rel = Path(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise PhotorealP1HeldoutPairingError("held-out review frame path escapes review root")
    result = (root / rel).resolve()
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise PhotorealP1HeldoutPairingError("held-out review frame path escapes review root") from exc
    return result


def _validate_semantic_alignment(
    value: Mapping[str, Any],
    *,
    teacher_input: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if value.get("format") != SEMANTIC_ALIGNMENT_FORMAT:
        raise PhotorealP1HeldoutPairingError("semantic camera alignment format/version mismatch")
    _strict_v1(value.get("version"), label="semantic camera alignment")
    if SEMANTIC_ALIGNMENT_VERSION != 1:
        raise PhotorealP1HeldoutPairingError("unsupported compiled semantic-alignment version")
    claimed = _sha(value.get("semantic_alignment_sha256"), label="semantic alignment SHA-256")
    if _digest(value, omit="semantic_alignment_sha256") != claimed:
        raise PhotorealP1HeldoutPairingError("semantic camera alignment digest mismatch")
    if _text(value.get("performer_id"), label="semantic alignment performer", maximum=256) != _text(
        teacher_input.get("performer_id"),
        label="teacher performer",
        maximum=256,
    ):
        raise PhotorealP1HeldoutPairingError("semantic camera alignment performer mismatch")
    if _text(value.get("selected_epoch_id"), label="semantic alignment epoch", maximum=256) != _text(
        teacher_input.get("selected_epoch_id"),
        label="teacher epoch",
        maximum=256,
    ):
        raise PhotorealP1HeldoutPairingError("semantic camera alignment epoch mismatch")
    if _sha(value.get("teacher_input_sha256"), label="semantic alignment teacher-input SHA-256") != _sha(
        teacher_input.get("teacher_input_sha256"),
        label="teacher input SHA-256",
    ):
        raise PhotorealP1HeldoutPairingError("semantic camera alignment teacher-input mismatch")
    for field, expected in (
        ("human_semantic_alignment_required", True),
        ("human_semantic_alignment_complete", True),
        ("semantic_camera_alignment_authority", True),
        ("human_visual_likeness_acceptance", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP1HeldoutPairingError(f"semantic camera alignment authority mismatch: {field}")

    raw = value.get("alignments")
    if not isinstance(raw, list) or not raw:
        raise PhotorealP1HeldoutPairingError("semantic camera alignment contains no alignments")
    alignments: dict[str, dict[str, Any]] = {}
    render_indices: set[int] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise PhotorealP1HeldoutPairingError("semantic camera alignment entry is invalid")
        label = _text(item.get("semantic_label"), label="semantic teacher label", maximum=128)
        if label in alignments:
            raise PhotorealP1HeldoutPairingError("semantic camera alignment repeats label")
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 50 or index in render_indices:
            raise PhotorealP1HeldoutPairingError("semantic camera alignment render index is invalid/duplicated")
        render_indices.add(index)
        relative = _text(item.get("render_relative_path"), label="semantic teacher render path")
        if relative != f"review/neutral-pose/{index}.png":
            raise PhotorealP1HeldoutPairingError("semantic camera alignment render path/index mismatch")
        alignments[label] = {
            "semantic_label": label,
            "teacher_render_index": index,
            "teacher_render_relative_path": relative,
            "teacher_render_sha256": _sha(item.get("render_sha256"), label="teacher render SHA-256"),
            "normalized_azimuth_degrees": item.get("normalized_azimuth_degrees"),
            "elevation_degrees": item.get("elevation_degrees"),
        }
    required_labels = {
        label
        for labels in CRITERION_ALLOWED_SEMANTIC_LABELS.values()
        for label in labels
    }
    if not required_labels.issubset(alignments):
        missing = sorted(required_labels - set(alignments))
        raise PhotorealP1HeldoutPairingError(
            "semantic camera alignment lacks required P1 labels: " + ", ".join(missing)
        )
    return alignments


def _teacher_eval_universe(teacher_input: Mapping[str, Any]) -> tuple[list[str], dict[tuple[str, str, str], dict[str, Any]]]:
    try:
        validated = validate_teacher_input_document(teacher_input)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealP1HeldoutPairingError(f"teacher input strict readback failed: {exc}") from exc
    if validated.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise PhotorealP1HeldoutPairingError("teacher input evaluation isolation is invalid")
    if validated.get("held_out_view_coverage_missing") != []:
        raise PhotorealP1HeldoutPairingError("teacher input held-out coverage is incomplete")
    if validated.get("human_visual_acceptance_required") is not True:
        raise PhotorealP1HeldoutPairingError("teacher input removed human visual acceptance")
    if validated.get("photoreal_acceptance_authority") is not False or validated.get("production_activation") is not False:
        raise PhotorealP1HeldoutPairingError("teacher input crossed downstream authority")

    required_raw = validated.get("held_out_view_coverage_required")
    if not isinstance(required_raw, list) or not required_raw:
        raise PhotorealP1HeldoutPairingError("teacher input has no held-out P1 coverage requirements")
    required = sorted({_text(item, label="held-out P1 criterion", maximum=64) for item in required_raw})
    unsupported = sorted(set(required) - set(CRITERION_ALLOWED_SEMANTIC_LABELS))
    if unsupported:
        raise PhotorealP1HeldoutPairingError(
            "teacher input contains unsupported P1 coverage criteria: " + ", ".join(unsupported)
        )

    observations_raw = validated.get("held_out_evaluation_observations")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise PhotorealP1HeldoutPairingError("teacher input has no held-out evaluation observations")
    observations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in observations_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealP1HeldoutPairingError("teacher input held-out observation is invalid")
        if _text(raw.get("split"), label="held-out split", maximum=32) != "evaluation":
            raise PhotorealP1HeldoutPairingError("teacher input held-out observation is not evaluation split")
        group_id = _text(raw.get("group_id"), label="held-out group id")
        source_key = _text(raw.get("source_key"), label="held-out source key")
        frame_sha = _sha(raw.get("frame_sha256"), label="held-out frame SHA-256")
        source_ref = _source_ref(source_key)
        key = (group_id, source_ref, frame_sha)
        if key in observations:
            raise PhotorealP1HeldoutPairingError("teacher input repeats held-out frame within source/group")
        coverage_raw = raw.get("coverage")
        if not isinstance(coverage_raw, list) or not coverage_raw:
            raise PhotorealP1HeldoutPairingError("teacher input held-out observation coverage is invalid")
        observations[key] = {
            "group_id": group_id,
            "source_key": source_key,
            "source_ref": source_ref,
            "frame_sha256": frame_sha,
            "view_bin": _text(raw.get("view_bin"), label="held-out view bin", maximum=64),
            "coverage": sorted({_text(item, label="held-out coverage", maximum=64) for item in coverage_raw}),
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": _text(raw.get("eye"), label="held-out eye", maximum=16),
        }
    return required, observations


def _review_eval_candidates(
    manifest: Mapping[str, Any],
    review_root: Path,
    *,
    teacher_observations: Mapping[tuple[str, str, str], Mapping[str, Any]],
    performer_id: str,
) -> list[dict[str, Any]]:
    if manifest.get("format") != REVIEW_MANIFEST_FORMAT:
        raise PhotorealP1HeldoutPairingError("appearance review manifest format/version mismatch")
    _strict_v1(manifest.get("version"), label="appearance review manifest")
    if REVIEW_MANIFEST_VERSION != 1:
        raise PhotorealP1HeldoutPairingError("unsupported compiled appearance-review version")
    if _text(manifest.get("performer_id"), label="appearance review performer", maximum=256) != performer_id:
        raise PhotorealP1HeldoutPairingError("appearance review performer mismatch")
    for field, expected in (
        ("source_paths_disclosed", False),
        ("source_media_rehash_performed", False),
        ("exact_p0_frame_hashes_reproduced", True),
        ("review_only", True),
        ("human_appearance_epoch_review_required", True),
        ("teacher_input_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP1HeldoutPairingError(f"appearance review authority mismatch: {field}")
    review_index = review_root / "review-index.html"
    if _sha(manifest.get("review_index_sha256"), label="appearance review HTML SHA-256") != _sha256_file(review_index):
        raise PhotorealP1HeldoutPairingError("appearance review HTML bytes changed")

    groups = manifest.get("groups")
    if not isinstance(groups, list) or not groups:
        raise PhotorealP1HeldoutPairingError("appearance review manifest contains no groups")
    candidates: list[dict[str, Any]] = []
    matched_teacher_keys: set[tuple[str, str]] = set()
    seen_frame_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, Mapping):
            raise PhotorealP1HeldoutPairingError("appearance review group is invalid")
        if group.get("split") != "evaluation":
            continue
        group_id = _text(group.get("group_id"), label="appearance review group id")
        frames = group.get("frames")
        if not isinstance(frames, list) or not frames:
            raise PhotorealP1HeldoutPairingError("appearance evaluation group contains no frames")
        for raw in frames:
            if not isinstance(raw, Mapping):
                raise PhotorealP1HeldoutPairingError("appearance evaluation frame is invalid")
            frame_id = _text(raw.get("frame_id"), label="appearance review frame id", maximum=128)
            if frame_id in seen_frame_ids:
                raise PhotorealP1HeldoutPairingError("appearance review repeats frame id")
            seen_frame_ids.add(frame_id)
            frame_sha = _sha(raw.get("frame_sha256"), label="appearance review frame SHA-256")
            source_ref = _text(raw.get("source_ref"), label="appearance review source ref", maximum=20)
            key = (group_id, source_ref, frame_sha)
            teacher = teacher_observations.get(key)
            if teacher is None:
                continue
            if source_ref != teacher["source_ref"]:
                raise PhotorealP1HeldoutPairingError("appearance review source reference differs from teacher input")
            if _text(raw.get("view_bin"), label="appearance review view bin", maximum=64) != teacher["view_bin"]:
                raise PhotorealP1HeldoutPairingError("appearance review view bin differs from teacher input")
            coverage_raw = raw.get("coverage")
            if not isinstance(coverage_raw, list):
                raise PhotorealP1HeldoutPairingError("appearance review coverage is invalid")
            coverage = sorted({_text(item, label="appearance review coverage", maximum=64) for item in coverage_raw})
            if coverage != teacher["coverage"]:
                raise PhotorealP1HeldoutPairingError("appearance review coverage differs from teacher input")
            relative = _text(raw.get("relative_path"), label="appearance review frame path")
            frame_path = _safe_review_path(review_root, relative)
            png_sha = _sha(raw.get("staged_png_sha256"), label="appearance review PNG SHA-256")
            if png_sha != _sha256_file(frame_path):
                raise PhotorealP1HeldoutPairingError("appearance review PNG bytes changed")
            candidates.append(
                {
                    "frame_id": frame_id,
                    "group_id": group_id,
                    "source_ref": teacher["source_ref"],
                    "frame_sha256": frame_sha,
                    "view_bin": teacher["view_bin"],
                    "coverage": coverage,
                    "timestamp_seconds": teacher["timestamp_seconds"],
                    "eye": teacher["eye"],
                    "review_relative_path": relative,
                    "review_png_sha256": png_sha,
                    "width": raw.get("width"),
                    "height": raw.get("height"),
                }
            )
            matched_teacher_keys.add(key)

    if matched_teacher_keys != set(teacher_observations):
        missing = len(set(teacher_observations) - matched_teacher_keys)
        raise PhotorealP1HeldoutPairingError(
            f"appearance review pack does not reproduce complete selected held-out teacher universe ({missing} missing)"
        )
    candidates.sort(key=lambda item: (item["group_id"], item["view_bin"], item["frame_id"]))
    return candidates


def build_p1_pairing_handoff(
    teacher_input: Mapping[str, Any],
    semantic_alignment: Mapping[str, Any],
    review_manifest: Mapping[str, Any],
    review_root: str | Path,
) -> dict[str, Any]:
    performer_id = _text(teacher_input.get("performer_id"), label="teacher performer", maximum=256)
    required, observations = _teacher_eval_universe(teacher_input)
    semantic = _validate_semantic_alignment(semantic_alignment, teacher_input=teacher_input)
    root = Path(review_root).expanduser().resolve()
    canonical_manifest_path = root / "appearance-epoch-visual-review-manifest.json"
    canonical_manifest = _read_json(canonical_manifest_path, label="canonical appearance review manifest")
    if dict(review_manifest) != canonical_manifest:
        raise PhotorealP1HeldoutPairingError(
            "supplied appearance review manifest differs from canonical review-root manifest"
        )
    candidates = _review_eval_candidates(
        canonical_manifest,
        root,
        teacher_observations=observations,
        performer_id=performer_id,
    )
    by_criterion = {
        criterion: [item["frame_id"] for item in candidates if criterion in item["coverage"]]
        for criterion in required
    }
    empty = sorted(criterion for criterion, ids in by_criterion.items() if not ids)
    if empty:
        raise PhotorealP1HeldoutPairingError(
            "selected held-out review pack lacks P1 criteria: " + ", ".join(empty)
        )

    semantic_views = [
        semantic[label]
        for label in sorted(semantic)
        if label in {item for labels in CRITERION_ALLOWED_SEMANTIC_LABELS.values() for item in labels}
    ]
    handoff: dict[str, Any] = {
        "format": HANDOFF_FORMAT,
        "version": HANDOFF_VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": _text(teacher_input.get("selected_epoch_id"), label="teacher epoch", maximum=256),
        "teacher_input_sha256": _sha(teacher_input.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "semantic_alignment_sha256": _sha(
            semantic_alignment.get("semantic_alignment_sha256"),
            label="semantic alignment SHA-256",
        ),
        "appearance_review_manifest_file_sha256": _sha256_file(canonical_manifest_path),
        "required_p1_criteria": required,
        "criterion_allowed_teacher_semantic_labels": {
            criterion: list(CRITERION_ALLOWED_SEMANTIC_LABELS[criterion])
            for criterion in required
        },
        "candidate_held_out_frames": candidates,
        "candidate_held_out_frame_ids_by_criterion": by_criterion,
        "semantic_teacher_views": semantic_views,
        "operator_requirements": {
            "assign_every_required_p1_criterion": True,
            "select_hash_bound_teacher_semantic_view": True,
            "select_hash_bound_held_out_reference_frame": True,
            "inspect_orientation_match_humanly": True,
            "keep_likeness_acceptance_separate": True,
        },
        "human_pairing_required": True,
        "human_pairing_complete": False,
        "held_out_pairing_authority": False,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    handoff["p1_pairing_handoff_sha256"] = _digest(handoff, omit="p1_pairing_handoff_sha256")
    return handoff


def record_p1_pairing(
    handoff: Mapping[str, Any],
    *,
    selections: Mapping[str, Mapping[str, str]],
    reviewed_by: str,
    review_notes: str,
    approve_human_review: bool,
) -> dict[str, Any]:
    if handoff.get("format") != HANDOFF_FORMAT:
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff format/version mismatch")
    _strict_v1(handoff.get("version"), label="P1 pairing handoff")
    claimed = _sha(handoff.get("p1_pairing_handoff_sha256"), label="P1 pairing handoff SHA-256")
    if _digest(handoff, omit="p1_pairing_handoff_sha256") != claimed:
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff digest mismatch")
    if approve_human_review is not True:
        raise PhotorealP1HeldoutPairingError("explicit human P1 pairing approval is required")
    for field, expected in (
        ("human_pairing_required", True),
        ("human_pairing_complete", False),
        ("held_out_pairing_authority", False),
        ("human_visual_likeness_acceptance", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if handoff.get(field) is not expected:
            raise PhotorealP1HeldoutPairingError(f"P1 pairing handoff authority mismatch: {field}")

    required_raw = handoff.get("required_p1_criteria")
    if not isinstance(required_raw, list) or not required_raw:
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff has no required criteria")
    required = [_text(item, label="required P1 criterion", maximum=64) for item in required_raw]
    if set(selections) != set(required):
        raise PhotorealP1HeldoutPairingError("P1 pairing must select every required criterion exactly once")

    raw_frames = handoff.get("candidate_held_out_frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff has no held-out frame candidates")
    frames = {
        _text(item.get("frame_id"), label="held-out frame id", maximum=128): item
        for item in raw_frames
        if isinstance(item, Mapping)
    }
    raw_semantic = handoff.get("semantic_teacher_views")
    if not isinstance(raw_semantic, list) or not raw_semantic:
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff has no semantic teacher views")
    semantic = {
        _text(item.get("semantic_label"), label="semantic teacher label", maximum=128): item
        for item in raw_semantic
        if isinstance(item, Mapping)
    }
    allowed_raw = handoff.get("criterion_allowed_teacher_semantic_labels")
    if not isinstance(allowed_raw, Mapping):
        raise PhotorealP1HeldoutPairingError("P1 pairing handoff has no semantic-label policy")

    pairs: list[dict[str, Any]] = []
    for criterion in required:
        selection = selections.get(criterion)
        if not isinstance(selection, Mapping) or set(selection) != {"semantic_label", "frame_id"}:
            raise PhotorealP1HeldoutPairingError(f"P1 pairing selection is invalid: {criterion}")
        semantic_label = _text(selection.get("semantic_label"), label="selected teacher semantic label", maximum=128)
        frame_id = _text(selection.get("frame_id"), label="selected held-out frame id", maximum=128)
        allowed = allowed_raw.get(criterion)
        if not isinstance(allowed, list) or semantic_label not in allowed:
            raise PhotorealP1HeldoutPairingError(
                f"selected teacher semantic label is not valid for criterion: {criterion}"
            )
        teacher_view = semantic.get(semantic_label)
        frame = frames.get(frame_id)
        if teacher_view is None or frame is None:
            raise PhotorealP1HeldoutPairingError(f"P1 pairing selection references unknown evidence: {criterion}")
        coverage = frame.get("coverage")
        if not isinstance(coverage, list) or criterion not in coverage:
            raise PhotorealP1HeldoutPairingError(
                f"selected held-out frame does not cover criterion: {criterion}"
            )
        pairs.append(
            {
                "criterion": criterion,
                "teacher_semantic_label": semantic_label,
                "teacher_render_index": teacher_view["teacher_render_index"],
                "teacher_render_relative_path": teacher_view["teacher_render_relative_path"],
                "teacher_render_sha256": teacher_view["teacher_render_sha256"],
                "held_out_frame_id": frame_id,
                "held_out_group_id": frame["group_id"],
                "held_out_source_ref": frame["source_ref"],
                "held_out_frame_sha256": frame["frame_sha256"],
                "held_out_view_bin": frame["view_bin"],
                "held_out_review_relative_path": frame["review_relative_path"],
                "held_out_review_png_sha256": frame["review_png_sha256"],
            }
        )

    reviewer = _text(reviewed_by, label="P1 pairing reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealP1HeldoutPairingError("P1 pairing review notes are invalid")
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": _text(handoff.get("performer_id"), label="P1 pairing performer", maximum=256),
        "selected_epoch_id": _text(handoff.get("selected_epoch_id"), label="P1 pairing epoch", maximum=256),
        "teacher_input_sha256": _sha(handoff.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "semantic_alignment_sha256": _sha(
            handoff.get("semantic_alignment_sha256"),
            label="semantic alignment SHA-256",
        ),
        "p1_pairing_handoff_sha256": claimed,
        "pairs": pairs,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "human_pairing_required": True,
        "human_pairing_complete": True,
        "held_out_pairing_authority": True,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p1_pairing_sha256"] = _digest(receipt, omit="p1_pairing_sha256")
    return receipt


def _parse_selection(values: Sequence[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        parts = value.split("=", 2)
        if len(parts) != 3:
            raise PhotorealP1HeldoutPairingError(
                "pairing selection must use CRITERION=SEMANTIC_LABEL=FRAME_ID"
            )
        criterion, semantic_label, frame_id = (part.strip() for part in parts)
        if not criterion or not semantic_label or not frame_id or criterion in result:
            raise PhotorealP1HeldoutPairingError("pairing selection is empty/duplicated")
        result[criterion] = {
            "semantic_label": semantic_label,
            "frame_id": frame_id,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and record human P1 teacher/held-out evidence pairing without granting likeness acceptance."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--teacher-input", type=Path, required=True)
    handoff.add_argument("--semantic-alignment", type=Path, required=True)
    handoff.add_argument("--appearance-review-manifest", type=Path, required=True)
    handoff.add_argument("--appearance-review-root", type=Path, required=True)
    handoff.add_argument("--out", type=Path, required=True)

    record = sub.add_parser("record")
    record.add_argument("--handoff", type=Path, required=True)
    record.add_argument("--pair", action="append", default=[])
    record.add_argument("--reviewed-by", required=True)
    record.add_argument("--review-notes", required=True)
    record.add_argument("--approve-human-review", action="store_true")
    record.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "handoff":
            teacher_input = _read_json(args.teacher_input, label="teacher input")
            semantic_alignment = _read_json(args.semantic_alignment, label="semantic camera alignment")
            review_manifest_path = args.appearance_review_manifest.expanduser().resolve()
            review_root = args.appearance_review_root.expanduser().resolve()
            expected_manifest = review_root / "appearance-epoch-visual-review-manifest.json"
            if review_manifest_path != expected_manifest:
                raise PhotorealP1HeldoutPairingError(
                    "appearance review manifest must be the canonical file inside appearance review root"
                )
            manifest = _read_json(review_manifest_path, label="appearance review manifest")
            result = build_p1_pairing_handoff(
                teacher_input,
                semantic_alignment,
                manifest,
                review_root,
            )
            result["appearance_review_manifest_file_sha256"] = _sha256_file(review_manifest_path)
            result["p1_pairing_handoff_sha256"] = _digest(result, omit="p1_pairing_handoff_sha256")
            output = args.out.expanduser().resolve()
            if output.exists():
                existing = _read_json(output, label="P1 pairing handoff")
                if existing != result:
                    raise PhotorealP1HeldoutPairingError(
                        f"existing P1 pairing handoff differs from canonical state: {output}"
                    )
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
            print(
                json.dumps(
                    {
                        "status": "HUMAN_PAIRING_REQUIRED",
                        "required_p1_criteria": result["required_p1_criteria"],
                        "held_out_candidate_count": len(result["candidate_held_out_frames"]),
                        "human_visual_likeness_acceptance": False,
                        "photoreal_acceptance_authority": False,
                        "production_activation": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 2

        handoff_value = _read_json(args.handoff, label="P1 pairing handoff")
        selections = _parse_selection(list(args.pair))
        receipt = record_p1_pairing(
            handoff_value,
            selections=selections,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_review=args.approve_human_review,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            raise PhotorealP1HeldoutPairingError(f"P1 pairing receipt already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "PAIRING_RECORDED",
                    "pair_count": len(receipt["pairs"]),
                    "held_out_pairing_authority": True,
                    "human_visual_likeness_acceptance": False,
                    "photoreal_acceptance_authority": False,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PhotorealP1HeldoutPairingError as exc:
        print(f"BodyRig P1 held-out pairing: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
