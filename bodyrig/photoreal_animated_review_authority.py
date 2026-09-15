from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animated_review_plan import (
    PhotorealAnimatedReviewPlanError,
    REFERENCE_CATALOG_FIELDS,
    REFERENCE_CATALOG_FORMAT,
    REFERENCE_OBSERVATION_FIELDS,
    REFERENCE_SOURCE_FIELDS,
    build_animated_review_plan,
)

VERSION = 1


class PhotorealAnimatedReviewAuthorityError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimatedReviewAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimatedReviewAuthorityError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedReviewAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimatedReviewAuthorityError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedReviewAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimatedReviewAuthorityError(f"{label} is invalid")
    return clean


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimatedReviewAuthorityError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealAnimatedReviewAuthorityError(f"{label} version must be numeric v1")


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimatedReviewAuthorityError("held-out observation timestamp is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealAnimatedReviewAuthorityError("held-out observation timestamp is invalid")
    return round(result, 6)


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


def validate_motion_reference_catalog(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != REFERENCE_CATALOG_FIELDS:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog fields must match v1 exactly")
    if value.get("format") != REFERENCE_CATALOG_FORMAT:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog format mismatch")
    _numeric_v1(value.get("version"), label="held-out reference catalog")
    declared = _sha(
        value.get("held_out_reference_catalog_sha256"), label="held-out reference catalog SHA-256"
    )
    if declared != _digest_without(value, "held_out_reference_catalog_sha256"):
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog SHA-256 does not match content")

    if value.get("coverage_authority") != "core-frame-index-v1":
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog coverage authority mismatch")
    if value.get("teacher_process_disclosure") is not False or value.get("source_paths_build_private") is not True:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog disclosure boundary is invalid")
    if value.get("reference_bytes_materialized") is not False:
        raise PhotorealAnimatedReviewAuthorityError("motion-review planning requires pre-materialization reference catalog")
    if value.get("reference_frame_hashes_verified") is not False:
        raise PhotorealAnimatedReviewAuthorityError("motion-review planning reference catalog phase is invalid")
    if value.get("human_reference_selection_required") is not True:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog removed human selection authority")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog crossed photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog removed human visual acceptance")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog build/runtime boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog crossed production authority")

    sources = value.get("held_out_sources")
    observations = value.get("held_out_observations")
    if not isinstance(sources, list) or not sources or not isinstance(observations, list) or not observations:
        raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog source/observation universe is empty")
    source_count = value.get("held_out_source_count")
    observation_count = value.get("held_out_observation_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count != len(sources):
        raise PhotorealAnimatedReviewAuthorityError("held-out reference source count mismatch")
    if isinstance(observation_count, bool) or not isinstance(observation_count, int) or observation_count != len(observations):
        raise PhotorealAnimatedReviewAuthorityError("held-out reference observation count mismatch")

    source_groups: dict[str, str] = {}
    for raw in sources:
        if not isinstance(raw, Mapping) or set(raw) != REFERENCE_SOURCE_FIELDS:
            raise PhotorealAnimatedReviewAuthorityError("held-out source fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="held-out source key")
        if source_key in source_groups:
            raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog repeats source key")
        group_id = _text(raw.get("group_id"), label="held-out source group")
        if raw.get("kind") not in {"video", "image"}:
            raise PhotorealAnimatedReviewAuthorityError("held-out source kind is invalid")
        size = raw.get("size_bytes")
        width = raw.get("width")
        height = raw.get("height")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealAnimatedReviewAuthorityError("held-out source size is invalid")
        if isinstance(width, bool) or not isinstance(width, int) or width < 0:
            raise PhotorealAnimatedReviewAuthorityError("held-out source width is invalid")
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise PhotorealAnimatedReviewAuthorityError("held-out source height is invalid")
        _text(raw.get("resolved_path"), label="held-out source path", maximum=32768)
        _sha(raw.get("sha256"), label="held-out source SHA-256")
        _text(raw.get("projection"), label="held-out source projection", maximum=128)
        _text(raw.get("stereo_layout"), label="held-out source stereo layout", maximum=128)
        source_groups[source_key] = group_id

    seen_ids: set[str] = set()
    for raw in observations:
        if not isinstance(raw, Mapping) or set(raw) != REFERENCE_OBSERVATION_FIELDS:
            raise PhotorealAnimatedReviewAuthorityError("held-out observation fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="held-out observation source key")
        group_id = _text(raw.get("group_id"), label="held-out observation group")
        if source_key not in source_groups or source_groups[source_key] != group_id:
            raise PhotorealAnimatedReviewAuthorityError("held-out observation source/group binding mismatch")
        frame_sha = _sha(raw.get("frame_sha256"), label="held-out observation frame SHA-256")
        timestamp = _timestamp(raw.get("timestamp_seconds"))
        eye = raw.get("eye")
        if eye not in {"mono", "left", "right"}:
            raise PhotorealAnimatedReviewAuthorityError("held-out observation eye is invalid")
        observation_id = _sha(raw.get("observation_id"), label="held-out observation id")
        expected_id = _observation_id(
            source_key=source_key,
            frame_sha256=frame_sha,
            timestamp_seconds=timestamp,
            eye=str(eye),
        )
        if observation_id != expected_id:
            raise PhotorealAnimatedReviewAuthorityError("held-out observation id does not match source/frame/timestamp/eye authority")
        if observation_id in seen_ids:
            raise PhotorealAnimatedReviewAuthorityError("held-out reference catalog repeats observation id")
        seen_ids.add(observation_id)
        _text(raw.get("view_bin"), label="held-out observation view bin", maximum=64)
        coverage = raw.get("coverage")
        if not isinstance(coverage, list) or any(not isinstance(item, str) or not item for item in coverage):
            raise PhotorealAnimatedReviewAuthorityError("held-out observation coverage is invalid")
        if raw.get("reference_bytes_materialized") is not False or raw.get("reference_frame_hash_verified") is not False:
            raise PhotorealAnimatedReviewAuthorityError("held-out observation crossed pre-materialization phase authority")

    return dict(value)


def build_animated_review_plan_files_strict(
    animation_execution_receipt_path: str | Path,
    reference_catalog_path: str | Path,
    selection_input_path: str | Path,
    animation_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    execution = _read_json(animation_execution_receipt_path, label="animation execution receipt")
    catalog = _read_json(reference_catalog_path, label="held-out reference catalog")
    selections = _read_json(selection_input_path, label="animated review selection input")
    validate_motion_reference_catalog(catalog)
    try:
        result = build_animated_review_plan(
            execution,
            catalog,
            selections,
            animation_output_root=animation_output_root,
        )
    except PhotorealAnimatedReviewPlanError as exc:
        raise PhotorealAnimatedReviewAuthorityError(str(exc)) from exc
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAnimatedReviewAuthorityError(f"animated review plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
