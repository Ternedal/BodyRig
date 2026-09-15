from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-teacher-held-out-reference-catalog"
VERSION = 1
INPUT_FORMAT = "bodyrig-photoreal-teacher-input"
INPUT_VERSION = 1
_SOURCE_FIELDS = {
    "source_key",
    "group_id",
    "kind",
    "resolved_path",
    "size_bytes",
    "sha256",
    "information_score",
    "width",
    "height",
    "projection",
    "stereo_layout",
}
_OBSERVATION_FIELDS = {
    "source_key",
    "group_id",
    "split",
    "frame_sha256",
    "timestamp_seconds",
    "eye",
    "view_bin",
    "coverage",
}


class PhotorealTeacherReviewReferenceError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherReviewReferenceError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherReviewReferenceError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    return result


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherReviewReferenceError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealTeacherReviewReferenceError(f"{label} version must be numeric v1")


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    return value


def _timestamp(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    return round(result, 6)


def _strings(value: Any, *, label: str, require_nonempty: bool) -> list[str]:
    if not isinstance(value, list) or (require_nonempty and not value):
        raise PhotorealTeacherReviewReferenceError(f"{label} is invalid")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = _text(raw, label=label, maximum=64)
        if item in seen:
            raise PhotorealTeacherReviewReferenceError(f"{label} contains duplicates")
        seen.add(item)
        result.append(item)
    return sorted(result)


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _observation_id(*, source_key: str, frame_sha256: str, timestamp_seconds: float | None, eye: str) -> str:
    payload = {
        "source_key": source_key,
        "frame_sha256": frame_sha256,
        "timestamp_seconds": timestamp_seconds,
        "eye": eye,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_held_out_reference_catalog(teacher_input: Mapping[str, Any]) -> dict[str, Any]:
    if teacher_input.get("format") != INPUT_FORMAT:
        raise PhotorealTeacherReviewReferenceError("teacher input format mismatch")
    _numeric_v1(teacher_input.get("version"), label="teacher input")
    performer_id = _text(teacher_input.get("performer_id"), label="teacher performer id", maximum=256)
    selected_epoch_id = _text(
        teacher_input.get("selected_epoch_id"), label="teacher selected epoch id", maximum=256
    )
    declared_input_sha = _sha(teacher_input.get("teacher_input_sha256"), label="teacher input SHA-256")
    unhashed = dict(teacher_input)
    unhashed.pop("teacher_input_sha256", None)
    if _digest(unhashed) != declared_input_sha:
        raise PhotorealTeacherReviewReferenceError("teacher input SHA-256 does not match manifest content")

    if teacher_input.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise PhotorealTeacherReviewReferenceError("teacher input evaluation isolation is invalid")
    if teacher_input.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherReviewReferenceError("teacher input does not authorize training")
    if teacher_input.get("photoreal_acceptance_authority") is not False:
        raise PhotorealTeacherReviewReferenceError("teacher input crossed photoreal authority")
    if teacher_input.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherReviewReferenceError("teacher input removed human visual acceptance")
    if teacher_input.get("build_only") is not True or teacher_input.get("runtime_dependency") is not False:
        raise PhotorealTeacherReviewReferenceError("teacher input build/runtime authority boundary is invalid")
    if teacher_input.get("production_activation") is not False:
        raise PhotorealTeacherReviewReferenceError("teacher input crossed production authority")
    if teacher_input.get("held_out_view_coverage_missing") != []:
        raise PhotorealTeacherReviewReferenceError("teacher input held-out view coverage is incomplete")

    source_values = teacher_input.get("held_out_evaluation_sources")
    if not isinstance(source_values, list) or not source_values:
        raise PhotorealTeacherReviewReferenceError("teacher input has no held-out evaluation sources")
    sources: list[dict[str, Any]] = []
    source_groups: dict[str, str] = {}
    for raw in source_values:
        if not isinstance(raw, Mapping) or set(raw) != _SOURCE_FIELDS:
            raise PhotorealTeacherReviewReferenceError("held-out source fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="held-out source key")
        if source_key in source_groups:
            raise PhotorealTeacherReviewReferenceError("teacher input repeats held-out source key")
        group_id = _text(raw.get("group_id"), label="held-out source group")
        kind = raw.get("kind")
        if kind not in {"video", "image"}:
            raise PhotorealTeacherReviewReferenceError("held-out source kind is invalid")
        size_bytes = _positive_int(raw.get("size_bytes"), label="held-out source size")
        width = raw.get("width")
        height = raw.get("height")
        if isinstance(width, bool) or not isinstance(width, int) or width < 0:
            raise PhotorealTeacherReviewReferenceError("held-out source width is invalid")
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise PhotorealTeacherReviewReferenceError("held-out source height is invalid")
        source = {
            "source_key": source_key,
            "group_id": group_id,
            "kind": kind,
            "resolved_path": _text(raw.get("resolved_path"), label="held-out resolved path", maximum=32768),
            "size_bytes": size_bytes,
            "sha256": _sha(raw.get("sha256"), label="held-out source SHA-256"),
            "width": width,
            "height": height,
            "projection": _text(raw.get("projection"), label="held-out projection", maximum=128),
            "stereo_layout": _text(raw.get("stereo_layout"), label="held-out stereo layout", maximum=128),
        }
        source_groups[source_key] = group_id
        sources.append(source)

    observation_values = teacher_input.get("held_out_evaluation_observations")
    if not isinstance(observation_values, list) or not observation_values:
        raise PhotorealTeacherReviewReferenceError("teacher input has no held-out evaluation observations")
    observations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    observed_sources: set[str] = set()
    coverage_to_ids: dict[str, list[str]] = {}
    for raw in observation_values:
        if not isinstance(raw, Mapping) or set(raw) != _OBSERVATION_FIELDS:
            raise PhotorealTeacherReviewReferenceError("held-out observation fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="held-out observation source key")
        if source_key not in source_groups:
            raise PhotorealTeacherReviewReferenceError("held-out observation references unknown source")
        group_id = _text(raw.get("group_id"), label="held-out observation group")
        if group_id != source_groups[source_key]:
            raise PhotorealTeacherReviewReferenceError("held-out observation group/source binding mismatch")
        if raw.get("split") != "evaluation":
            raise PhotorealTeacherReviewReferenceError("held-out observation is not evaluation split")
        frame_sha = _sha(raw.get("frame_sha256"), label="held-out frame SHA-256")
        timestamp = _timestamp(raw.get("timestamp_seconds"), label="held-out timestamp")
        eye = raw.get("eye")
        if eye not in {"mono", "left", "right"}:
            raise PhotorealTeacherReviewReferenceError("held-out observation eye is invalid")
        view_bin = _text(raw.get("view_bin"), label="held-out view bin", maximum=64)
        coverage = _strings(raw.get("coverage"), label="held-out coverage", require_nonempty=False)
        observation_id = _observation_id(
            source_key=source_key,
            frame_sha256=frame_sha,
            timestamp_seconds=timestamp,
            eye=str(eye),
        )
        if observation_id in seen_ids:
            raise PhotorealTeacherReviewReferenceError("teacher input repeats held-out observation")
        seen_ids.add(observation_id)
        observed_sources.add(source_key)
        item = {
            "observation_id": observation_id,
            "source_key": source_key,
            "group_id": group_id,
            "frame_sha256": frame_sha,
            "timestamp_seconds": timestamp,
            "eye": eye,
            "view_bin": view_bin,
            "coverage": coverage,
            "reference_bytes_materialized": False,
            "reference_frame_hash_verified": False,
        }
        observations.append(item)
        for label in coverage:
            coverage_to_ids.setdefault(label, []).append(observation_id)

    if observed_sources != set(source_groups):
        raise PhotorealTeacherReviewReferenceError("every held-out source must have at least one held-out observation")
    expected_source_count = _positive_int(
        teacher_input.get("held_out_evaluation_source_count"), label="held-out evaluation source count"
    )
    expected_observation_count = _positive_int(
        teacher_input.get("held_out_evaluation_observation_count"), label="held-out evaluation observation count"
    )
    if expected_source_count != len(sources):
        raise PhotorealTeacherReviewReferenceError("held-out evaluation source count mismatch")
    if expected_observation_count != len(observations):
        raise PhotorealTeacherReviewReferenceError("held-out evaluation observation count mismatch")

    required_coverage = _strings(
        teacher_input.get("held_out_view_coverage_required"),
        label="held-out required coverage",
        require_nonempty=True,
    )
    observed_coverage = _strings(
        teacher_input.get("held_out_view_coverage_observed"),
        label="held-out observed coverage",
        require_nonempty=True,
    )
    if not set(required_coverage).issubset(set(observed_coverage)):
        raise PhotorealTeacherReviewReferenceError("teacher input observed coverage does not satisfy required coverage")
    missing_candidates = [label for label in required_coverage if not coverage_to_ids.get(label)]
    if missing_candidates:
        raise PhotorealTeacherReviewReferenceError(
            "held-out required coverage has no reference candidates: " + ", ".join(missing_candidates)
        )

    sources.sort(key=lambda item: item["source_key"])
    observations.sort(
        key=lambda item: (
            item["source_key"],
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            str(item["eye"]),
            item["frame_sha256"],
        )
    )
    coverage_candidates = [
        {
            "coverage": label,
            "candidate_observation_ids": sorted(coverage_to_ids[label]),
            "candidate_count": len(coverage_to_ids[label]),
            "human_reference_selection_required": True,
        }
        for label in required_coverage
    ]

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": selected_epoch_id,
        "teacher_input_sha256": declared_input_sha,
        "held_out_source_count": len(sources),
        "held_out_observation_count": len(observations),
        "held_out_sources": sources,
        "held_out_observations": observations,
        "required_coverage": required_coverage,
        "observed_coverage": observed_coverage,
        "coverage_candidates": coverage_candidates,
        "coverage_authority": "core-frame-index-v1",
        "teacher_process_disclosure": False,
        "source_paths_build_private": True,
        "reference_bytes_materialized": False,
        "reference_frame_hashes_verified": False,
        "human_reference_selection_required": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["held_out_reference_catalog_sha256"] = _digest(result)
    return result


def build_held_out_reference_catalog_files(
    teacher_input_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    teacher_input = _read_json(teacher_input_path, label="photoreal teacher input")
    result = build_held_out_reference_catalog(teacher_input)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherReviewReferenceError(f"held-out reference catalog already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
