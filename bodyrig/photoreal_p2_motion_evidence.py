from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_animation_plan import (
    PhotorealP2AnimationPlanError,
    validate_p2_animation_plan,
)
from .photoreal_teacher_authority import validate_teacher_input_document
from .photoreal_teacher_runner import PhotorealTeacherRunnerError


HANDOFF_FORMAT = "bodyrig-photoreal-p2-motion-evidence-handoff"
HANDOFF_VERSION = 1
PRIVATE_INDEX_FORMAT = "bodyrig-photoreal-p2-motion-private-index"
PRIVATE_INDEX_VERSION = 1


class PhotorealP2MotionEvidenceError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionEvidenceError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionEvidenceError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionEvidenceError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionEvidenceError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2MotionEvidenceError(f"{label} is invalid")
    return result


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
        raise PhotorealP2MotionEvidenceError("P2 motion artifact cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _source_ref(source_key: str) -> str:
    return "src-" + hashlib.sha256(("bodyrig-p2-motion:" + source_key).encode("utf-8")).hexdigest()[:24]


def _group_ref(group_id: str) -> str:
    return "grp-" + hashlib.sha256(("bodyrig-p2-motion-group:" + group_id).encode("utf-8")).hexdigest()[:24]


def _source_observation_summary(
    source_key: str,
    observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = [item for item in observations if item.get("source_key") == source_key]
    if not selected:
        raise PhotorealP2MotionEvidenceError("motion candidate source has no authorized observations")
    view_bins = sorted({_text(item.get("view_bin"), label="motion view bin", maximum=64) for item in selected})
    coverage: set[str] = set()
    timestamp_count = 0
    for item in selected:
        raw_coverage = item.get("coverage")
        if not isinstance(raw_coverage, list):
            raise PhotorealP2MotionEvidenceError("motion observation coverage is invalid")
        coverage.update(_text(value, label="motion coverage", maximum=64) for value in raw_coverage)
        if item.get("timestamp_seconds") is not None:
            timestamp_count += 1
    return {
        "authorized_observation_count": len(selected),
        "timestamped_observation_count": timestamp_count,
        "view_bins": view_bins,
        "coverage": sorted(coverage),
    }


def _preparation_mode(source: Mapping[str, Any]) -> str:
    projection = _text(source.get("projection"), label="motion source projection", maximum=128).lower()
    stereo = _text(source.get("stereo_layout"), label="motion source stereo layout", maximum=128).lower()
    if projection == "flat" and stereo == "mono":
        return "direct-exavatar-video"
    return "exact-authorized-deprojection-required"


def _public_candidate(
    source: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    *,
    split: str,
) -> dict[str, Any]:
    source_key = _text(source.get("source_key"), label="motion source key", maximum=32768)
    group_id = _text(source.get("group_id"), label="motion source group", maximum=32768)
    kind = source.get("kind")
    if kind != "video":
        raise PhotorealP2MotionEvidenceError("P2 motion candidate must be video")
    size = source.get("size_bytes")
    width = source.get("width")
    height = source.get("height")
    information_score = source.get("information_score")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PhotorealP2MotionEvidenceError("motion source size is invalid")
    if isinstance(width, bool) or not isinstance(width, int) or width < 0:
        raise PhotorealP2MotionEvidenceError("motion source width is invalid")
    if isinstance(height, bool) or not isinstance(height, int) or height < 0:
        raise PhotorealP2MotionEvidenceError("motion source height is invalid")
    if isinstance(information_score, bool) or not isinstance(information_score, (int, float)):
        raise PhotorealP2MotionEvidenceError("motion source information score is invalid")
    score = float(information_score)
    if not math.isfinite(score) or score < 0:
        raise PhotorealP2MotionEvidenceError("motion source information score is invalid")
    result = {
        "source_ref": _source_ref(source_key),
        "group_ref": _group_ref(group_id),
        "split": split,
        "kind": "video",
        "source_sha256": _sha(source.get("sha256"), label="motion source SHA-256"),
        "size_bytes": size,
        "information_score": score,
        "width": width,
        "height": height,
        "projection": _text(source.get("projection"), label="motion source projection", maximum=128),
        "stereo_layout": _text(source.get("stereo_layout"), label="motion source stereo layout", maximum=128),
        "preparation_mode": _preparation_mode(source),
    }
    result.update(_source_observation_summary(source_key, observations))
    return result


def build_motion_evidence_handoff(
    teacher_input: Mapping[str, Any],
    p2_animation_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        validated_input = validate_teacher_input_document(teacher_input)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealP2MotionEvidenceError(f"teacher input strict readback failed: {exc}") from exc
    try:
        validated_plan = validate_p2_animation_plan(p2_animation_plan)
    except PhotorealP2AnimationPlanError as exc:
        raise PhotorealP2MotionEvidenceError(f"P2 animation plan strict readback failed: {exc}") from exc

    for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256"):
        if validated_plan.get(field) != validated_input.get(field):
            raise PhotorealP2MotionEvidenceError(f"P2 plan/teacher-input provenance mismatch: {field}")
    if validated_input.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise PhotorealP2MotionEvidenceError("teacher input lost held-out evaluation isolation")

    train_sources = validated_input.get("training_sources")
    eval_sources = validated_input.get("held_out_evaluation_sources")
    train_observations = validated_input.get("training_observations")
    eval_observations = validated_input.get("held_out_evaluation_observations")
    if not all(isinstance(value, list) for value in (train_sources, eval_sources, train_observations, eval_observations)):
        raise PhotorealP2MotionEvidenceError("teacher input motion source universe is invalid")

    driver_sources = [item for item in train_sources if isinstance(item, Mapping) and item.get("kind") == "video"]
    heldout_sources = [item for item in eval_sources if isinstance(item, Mapping) and item.get("kind") == "video"]
    if not driver_sources:
        raise PhotorealP2MotionEvidenceError("P2 requires at least one training-split video for motion driving")
    if not heldout_sources:
        raise PhotorealP2MotionEvidenceError("P2 requires at least one evaluation-split video for held-out motion validation")

    drivers = [
        _public_candidate(item, train_observations, split="train")
        for item in sorted(driver_sources, key=lambda value: str(value.get("source_key")))
    ]
    heldout = [
        _public_candidate(item, eval_observations, split="evaluation")
        for item in sorted(heldout_sources, key=lambda value: str(value.get("source_key")))
    ]

    private_entries: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for split, sources in (("train", driver_sources), ("evaluation", heldout_sources)):
        for source in sorted(sources, key=lambda value: str(value.get("source_key"))):
            source_key = _text(source.get("source_key"), label="private motion source key", maximum=32768)
            group_id = _text(source.get("group_id"), label="private motion source group", maximum=32768)
            ref = _source_ref(source_key)
            if ref in seen_refs:
                raise PhotorealP2MotionEvidenceError("P2 motion source reference collision")
            seen_refs.add(ref)
            private_entries.append(
                {
                    "source_ref": ref,
                    "group_ref": _group_ref(group_id),
                    "split": split,
                    "source_key": source_key,
                    "group_id": group_id,
                    "resolved_path": _text(
                        source.get("resolved_path"),
                        label="private motion source path",
                        maximum=32768,
                    ),
                    "source_sha256": _sha(source.get("sha256"), label="private motion source SHA-256"),
                    "size_bytes": source.get("size_bytes"),
                }
            )

    handoff: dict[str, Any] = {
        "format": HANDOFF_FORMAT,
        "version": HANDOFF_VERSION,
        "performer_id": _text(validated_input.get("performer_id"), label="motion performer id", maximum=256),
        "selected_epoch_id": _text(validated_input.get("selected_epoch_id"), label="motion epoch id", maximum=256),
        "teacher_input_sha256": _sha(validated_input.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "p2_animation_plan_sha256": _sha(
            validated_plan.get("p2_animation_plan_sha256"),
            label="P2 animation plan SHA-256",
        ),
        "motion_driver_candidates": drivers,
        "held_out_motion_validation_candidates": heldout,
        "motion_driver_candidate_count": len(drivers),
        "held_out_motion_validation_candidate_count": len(heldout),
        "operator_requirements": {
            "select_at_least_one_training_split_motion_driver": True,
            "select_at_least_one_evaluation_split_validation_source": True,
            "preserve_train_evaluation_group_disjointness": True,
            "never_use_evaluation_bytes_for_appearance_training": True,
            "require_exact_deprojection_before_fit_when_flagged": True,
            "record_human_selection": True,
        },
        "source_media_rehash_performed": False,
        "human_motion_source_selection_required": True,
        "human_motion_source_selection_complete": False,
        "p2_motion_input_authorized": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    handoff["p2_motion_evidence_handoff_sha256"] = _digest(
        handoff,
        omit="p2_motion_evidence_handoff_sha256",
    )

    private_index: dict[str, Any] = {
        "format": PRIVATE_INDEX_FORMAT,
        "version": PRIVATE_INDEX_VERSION,
        "performer_id": handoff["performer_id"],
        "selected_epoch_id": handoff["selected_epoch_id"],
        "teacher_input_sha256": handoff["teacher_input_sha256"],
        "p2_animation_plan_sha256": handoff["p2_animation_plan_sha256"],
        "p2_motion_evidence_handoff_sha256": handoff["p2_motion_evidence_handoff_sha256"],
        "entries": private_entries,
        "entry_count": len(private_entries),
        "build_private": True,
        "source_media_rehash_performed": False,
        "production_activation": False,
    }
    private_index["p2_motion_private_index_sha256"] = _digest(
        private_index,
        omit="p2_motion_private_index_sha256",
    )
    return (
        validate_motion_evidence_handoff(handoff),
        validate_private_motion_index(private_index, handoff=handoff),
    )


def _candidate_map(
    values: Any,
    *,
    expected_split: str,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionEvidenceError(f"{label} is invalid")
    result: dict[str, dict[str, Any]] = {}
    group_refs: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionEvidenceError(f"{label} entry is invalid")
        if "source_key" in raw or "resolved_path" in raw or "group_id" in raw:
            raise PhotorealP2MotionEvidenceError(f"{label} leaks private source identity")
        source_ref = _text(raw.get("source_ref"), label=f"{label} source ref", maximum=64)
        group_ref = _text(raw.get("group_ref"), label=f"{label} group ref", maximum=64)
        if not source_ref.startswith("src-") or not group_ref.startswith("grp-"):
            raise PhotorealP2MotionEvidenceError(f"{label} opaque reference is invalid")
        if source_ref in result:
            raise PhotorealP2MotionEvidenceError(f"{label} repeats source ref")
        if raw.get("split") != expected_split or raw.get("kind") != "video":
            raise PhotorealP2MotionEvidenceError(f"{label} split/kind mismatch")
        _sha(raw.get("source_sha256"), label=f"{label} source SHA-256")
        for field in ("size_bytes", "width", "height", "authorized_observation_count", "timestamped_observation_count"):
            value = raw.get(field)
            minimum = 1 if field in {"size_bytes", "authorized_observation_count"} else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise PhotorealP2MotionEvidenceError(f"{label} {field} is invalid")
        score = raw.get("information_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or float(score) < 0:
            raise PhotorealP2MotionEvidenceError(f"{label} information score is invalid")
        for field in ("projection", "stereo_layout"):
            _text(raw.get(field), label=f"{label} {field}", maximum=128)
        if raw.get("preparation_mode") not in {
            "direct-exavatar-video",
            "exact-authorized-deprojection-required",
        }:
            raise PhotorealP2MotionEvidenceError(f"{label} preparation mode is invalid")
        for field in ("view_bins", "coverage"):
            values_field = raw.get(field)
            if not isinstance(values_field, list) or values_field != sorted(set(values_field)):
                raise PhotorealP2MotionEvidenceError(f"{label} {field} is invalid")
            for item in values_field:
                _text(item, label=f"{label} {field}", maximum=64)
        result[source_ref] = dict(raw)
        group_refs.add(group_ref)
    return result


def validate_motion_evidence_handoff(handoff: Mapping[str, Any]) -> dict[str, Any]:
    if handoff.get("format") != HANDOFF_FORMAT or handoff.get("version") != HANDOFF_VERSION:
        raise PhotorealP2MotionEvidenceError("P2 motion evidence handoff format/version mismatch")
    claimed = _sha(
        handoff.get("p2_motion_evidence_handoff_sha256"),
        label="P2 motion evidence handoff SHA-256",
    )
    if _digest(handoff, omit="p2_motion_evidence_handoff_sha256") != claimed:
        raise PhotorealP2MotionEvidenceError("P2 motion evidence handoff digest mismatch")
    _text(handoff.get("performer_id"), label="P2 motion performer", maximum=256)
    _text(handoff.get("selected_epoch_id"), label="P2 motion epoch", maximum=256)
    _sha(handoff.get("teacher_input_sha256"), label="P2 motion teacher input SHA-256")
    _sha(handoff.get("p2_animation_plan_sha256"), label="P2 motion animation plan SHA-256")

    drivers = _candidate_map(
        handoff.get("motion_driver_candidates"),
        expected_split="train",
        label="P2 motion driver candidates",
    )
    heldout = _candidate_map(
        handoff.get("held_out_motion_validation_candidates"),
        expected_split="evaluation",
        label="P2 held-out motion candidates",
    )
    if set(drivers) & set(heldout):
        raise PhotorealP2MotionEvidenceError("P2 motion handoff source refs overlap train/evaluation")
    driver_groups = {item["group_ref"] for item in drivers.values()}
    eval_groups = {item["group_ref"] for item in heldout.values()}
    if driver_groups & eval_groups:
        raise PhotorealP2MotionEvidenceError("P2 motion handoff group refs overlap train/evaluation")
    if handoff.get("motion_driver_candidate_count") != len(drivers):
        raise PhotorealP2MotionEvidenceError("P2 motion driver candidate count mismatch")
    if handoff.get("held_out_motion_validation_candidate_count") != len(heldout):
        raise PhotorealP2MotionEvidenceError("P2 held-out motion candidate count mismatch")

    expected_requirements = {
        "select_at_least_one_training_split_motion_driver": True,
        "select_at_least_one_evaluation_split_validation_source": True,
        "preserve_train_evaluation_group_disjointness": True,
        "never_use_evaluation_bytes_for_appearance_training": True,
        "require_exact_deprojection_before_fit_when_flagged": True,
        "record_human_selection": True,
    }
    if handoff.get("operator_requirements") != expected_requirements:
        raise PhotorealP2MotionEvidenceError("P2 motion handoff operator requirements mismatch")
    for field, expected in (
        ("source_media_rehash_performed", False),
        ("human_motion_source_selection_required", True),
        ("human_motion_source_selection_complete", False),
        ("p2_motion_input_authorized", False),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if handoff.get(field) is not expected:
            raise PhotorealP2MotionEvidenceError(f"P2 motion handoff authority mismatch: {field}")
    return dict(handoff)


def validate_private_motion_index(
    private_index: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    validated_handoff = validate_motion_evidence_handoff(handoff)
    if private_index.get("format") != PRIVATE_INDEX_FORMAT or private_index.get("version") != PRIVATE_INDEX_VERSION:
        raise PhotorealP2MotionEvidenceError("private P2 motion index format/version mismatch")
    claimed = _sha(
        private_index.get("p2_motion_private_index_sha256"),
        label="private P2 motion index SHA-256",
    )
    if _digest(private_index, omit="p2_motion_private_index_sha256") != claimed:
        raise PhotorealP2MotionEvidenceError("private P2 motion index digest mismatch")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
    ):
        if private_index.get(field) != validated_handoff.get(field):
            raise PhotorealP2MotionEvidenceError(f"private P2 motion index provenance mismatch: {field}")
    if private_index.get("build_private") is not True:
        raise PhotorealP2MotionEvidenceError("private P2 motion index lost build-private marking")
    if private_index.get("source_media_rehash_performed") is not False:
        raise PhotorealP2MotionEvidenceError("private P2 motion index unexpectedly claims source rehash")
    if private_index.get("production_activation") is not False:
        raise PhotorealP2MotionEvidenceError("private P2 motion index crossed production authority")

    expected_public: dict[str, dict[str, Any]] = {}
    for raw in (
        list(validated_handoff["motion_driver_candidates"])
        + list(validated_handoff["held_out_motion_validation_candidates"])
    ):
        expected_public[raw["source_ref"]] = raw

    entries = private_index.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PhotorealP2MotionEvidenceError("private P2 motion index entries are invalid")
    if private_index.get("entry_count") != len(entries) or len(entries) != len(expected_public):
        raise PhotorealP2MotionEvidenceError("private P2 motion index count mismatch")
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionEvidenceError("private P2 motion index entry is invalid")
        source_ref = _text(raw.get("source_ref"), label="private P2 motion source ref", maximum=64)
        if source_ref in seen or source_ref not in expected_public:
            raise PhotorealP2MotionEvidenceError("private P2 motion index source universe mismatch")
        seen.add(source_ref)
        public = expected_public[source_ref]
        for field in ("group_ref", "split", "source_sha256", "size_bytes"):
            if raw.get(field) != public.get(field):
                raise PhotorealP2MotionEvidenceError(f"private/public P2 motion binding mismatch: {field}")
        _text(raw.get("source_key"), label="private P2 motion source key", maximum=32768)
        _text(raw.get("group_id"), label="private P2 motion group id", maximum=32768)
        _text(raw.get("resolved_path"), label="private P2 motion resolved path", maximum=32768)
    if seen != set(expected_public):
        raise PhotorealP2MotionEvidenceError("private P2 motion index source universe mismatch")
    return dict(private_index)


def _write_or_revalidate(path: Path, value: Mapping[str, Any], *, label: str, reuse_existing: bool) -> None:
    if path.exists():
        if not reuse_existing:
            raise PhotorealP2MotionEvidenceError(f"{label} already exists: {path}")
        existing = _read_json(path, label=label)
        if existing != dict(value):
            raise PhotorealP2MotionEvidenceError(f"existing {label} differs from canonical current state: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP2MotionEvidenceError(f"failed to persist {label}: {path}") from exc


def build_motion_evidence_handoff_files(
    teacher_input_path: str | Path,
    p2_animation_plan_path: str | Path,
    output_dir: str | Path,
    *,
    reuse_existing: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    teacher_input = _read_json(teacher_input_path, label="strict teacher input")
    p2_plan = _read_json(p2_animation_plan_path, label="P2 animation plan")
    handoff, private_index = build_motion_evidence_handoff(teacher_input, p2_plan)
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_or_revalidate(
        root / "p2-motion-evidence-handoff.json",
        handoff,
        label="P2 motion evidence handoff",
        reuse_existing=reuse_existing,
    )
    _write_or_revalidate(
        root / "private-motion-source-index.json",
        private_index,
        label="private P2 motion source index",
        reuse_existing=reuse_existing,
    )
    return handoff, private_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a path-private human handoff for P2 motion-driver and held-out validation source selection."
    )
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--p2-animation-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        handoff, private_index = build_motion_evidence_handoff_files(
            args.teacher_input,
            args.p2_animation_plan,
            args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2MotionEvidenceError as exc:
        print(f"BodyRig P2 motion evidence handoff: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "HUMAN_MOTION_SOURCE_SELECTION_REQUIRED",
                "motion_driver_candidate_count": handoff["motion_driver_candidate_count"],
                "held_out_motion_validation_candidate_count": handoff[
                    "held_out_motion_validation_candidate_count"
                ],
                "private_source_index_entry_count": private_index["entry_count"],
                "source_media_rehash_performed": False,
                "p2_motion_input_authorized": False,
                "p2_animation_execution_authorized": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
