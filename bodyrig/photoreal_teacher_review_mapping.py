from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

RENDER_SET_FORMAT = "bodyrig-photoreal-teacher-review-render-set"
REFERENCE_CATALOG_FORMAT = "bodyrig-photoreal-teacher-held-out-reference-catalog"
SELECTION_INPUT_FORMAT = "bodyrig-photoreal-teacher-review-selection-input"
OUTPUT_FORMAT = "bodyrig-photoreal-teacher-review-mapping"
VERSION = 1


class PhotorealTeacherReviewMappingError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherReviewMappingError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherReviewMappingError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewMappingError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherReviewMappingError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewMappingError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherReviewMappingError(f"{label} is invalid")
    return result


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherReviewMappingError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealTeacherReviewMappingError(f"{label} version must be numeric v1")


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_render_set(value: Mapping[str, Any]) -> tuple[str, str, str, dict[int, Mapping[str, Any]]]:
    if value.get("format") != RENDER_SET_FORMAT:
        raise PhotorealTeacherReviewMappingError("review render set format mismatch")
    _v1(value.get("version"), label="review render set")
    declared = _sha(value.get("review_render_set_sha256"), label="review render set SHA-256")
    if _digest(value, omit="review_render_set_sha256") != declared:
        raise PhotorealTeacherReviewMappingError("review render set digest mismatch")
    if value.get("render_bytes_verified") is not True or value.get("camera_geometry_authority") is not True:
        raise PhotorealTeacherReviewMappingError("review render set lacks byte/camera authority")
    if value.get("semantic_view_authority") is not False or value.get("human_semantic_view_mapping_required") is not True:
        raise PhotorealTeacherReviewMappingError("review render set semantic authority boundary is invalid")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealTeacherReviewMappingError("review render set crossed downstream authority")
    renders_raw = value.get("renders")
    if not isinstance(renders_raw, list) or len(renders_raw) != 50:
        raise PhotorealTeacherReviewMappingError("review render set must contain 50 renders")
    renders: dict[int, Mapping[str, Any]] = {}
    for raw in renders_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMappingError("review render entry is invalid")
        camera = raw.get("camera")
        if not isinstance(camera, Mapping):
            raise PhotorealTeacherReviewMappingError("review render camera is invalid")
        index = camera.get("orbit_index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 50:
            raise PhotorealTeacherReviewMappingError("review render orbit index is invalid")
        if index in renders:
            raise PhotorealTeacherReviewMappingError("review render set repeats orbit index")
        if raw.get("semantic_view_label") is not None or raw.get("semantic_view_authority") is not False:
            raise PhotorealTeacherReviewMappingError("review render already carries semantic authority")
        renders[index] = raw
    if set(renders) != set(range(50)):
        raise PhotorealTeacherReviewMappingError("review render orbit universe is incomplete")
    return (
        _text(value.get("performer_id"), label="render-set performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="render-set selected epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="render-set teacher input SHA-256"),
        renders,
    )


def _validate_reference_catalog(
    value: Mapping[str, Any],
) -> tuple[str, str, str, dict[str, Mapping[str, Any]], dict[str, set[str]], dict[str, Mapping[str, Any]]]:
    if value.get("format") != REFERENCE_CATALOG_FORMAT:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog format mismatch")
    _v1(value.get("version"), label="held-out reference catalog")
    declared = _sha(value.get("held_out_reference_catalog_sha256"), label="held-out reference catalog SHA-256")
    if _digest(value, omit="held_out_reference_catalog_sha256") != declared:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog digest mismatch")
    if value.get("teacher_process_disclosure") is not False or value.get("source_paths_build_private") is not True:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog privacy boundary is invalid")
    if value.get("reference_bytes_materialized") is not False or value.get("reference_frame_hashes_verified") is not False:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog unexpectedly claims materialized bytes")
    if value.get("human_reference_selection_required") is not True:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog removed human selection")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog crossed downstream authority")

    observations_raw = value.get("held_out_observations")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog has no observations")
    observations: dict[str, Mapping[str, Any]] = {}
    for raw in observations_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMappingError("held-out reference observation is invalid")
        observation_id = _sha(raw.get("observation_id"), label="held-out observation id")
        if observation_id in observations:
            raise PhotorealTeacherReviewMappingError("held-out reference catalog repeats observation id")
        observations[observation_id] = raw

    candidates_raw = value.get("coverage_candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog has no coverage candidates")
    candidates: dict[str, set[str]] = {}
    for raw in candidates_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMappingError("coverage candidate entry is invalid")
        coverage = _text(raw.get("coverage"), label="coverage candidate", maximum=64)
        if coverage in candidates:
            raise PhotorealTeacherReviewMappingError("held-out reference catalog repeats coverage candidate")
        ids_raw = raw.get("candidate_observation_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            raise PhotorealTeacherReviewMappingError("coverage candidate has no observation ids")
        ids = {_sha(item, label="coverage candidate observation id") for item in ids_raw}
        if len(ids) != len(ids_raw) or not ids.issubset(observations):
            raise PhotorealTeacherReviewMappingError("coverage candidate observation set is invalid")
        candidates[coverage] = ids

    sources_raw = value.get("held_out_sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog has no sources")
    sources: dict[str, Mapping[str, Any]] = {}
    for raw in sources_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherReviewMappingError("held-out source is invalid")
        key = _text(raw.get("source_key"), label="held-out source key")
        if key in sources:
            raise PhotorealTeacherReviewMappingError("held-out reference catalog repeats source key")
        sources[key] = raw

    required_raw = value.get("required_coverage")
    if not isinstance(required_raw, list) or not required_raw:
        raise PhotorealTeacherReviewMappingError("held-out reference catalog has no required coverage")
    required = [_text(item, label="required coverage", maximum=64) for item in required_raw]
    if len(set(required)) != len(required) or set(required) != set(candidates):
        raise PhotorealTeacherReviewMappingError("held-out required coverage/candidate universe mismatch")

    return (
        _text(value.get("performer_id"), label="reference-catalog performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="reference-catalog selected epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="reference-catalog teacher input SHA-256"),
        observations,
        candidates,
        sources,
    )


def build_review_mapping(
    render_set: Mapping[str, Any],
    reference_catalog: Mapping[str, Any],
    selection_input: Mapping[str, Any],
) -> dict[str, Any]:
    performer_id, epoch_id, teacher_input_sha, renders = _validate_render_set(render_set)
    ref_performer, ref_epoch, ref_teacher_input_sha, observations, candidates, sources = _validate_reference_catalog(reference_catalog)
    if (ref_performer, ref_epoch, ref_teacher_input_sha) != (performer_id, epoch_id, teacher_input_sha):
        raise PhotorealTeacherReviewMappingError("render/reference review lineage mismatch")

    if selection_input.get("format") != SELECTION_INPUT_FORMAT:
        raise PhotorealTeacherReviewMappingError("review selection input format mismatch")
    _v1(selection_input.get("version"), label="review selection input")
    reviewer = _text(selection_input.get("reviewer"), label="reviewer", maximum=256)
    if selection_input.get("operator_supplied") is not True:
        raise PhotorealTeacherReviewMappingError("review mapping must be explicitly operator supplied")
    raw_selections = selection_input.get("selections")
    if not isinstance(raw_selections, list) or not raw_selections:
        raise PhotorealTeacherReviewMappingError("review selection input has no selections")

    selected: dict[str, dict[str, Any]] = {}
    for raw in raw_selections:
        if not isinstance(raw, Mapping) or set(raw) != {"coverage", "render_orbit_index", "reference_observation_id"}:
            raise PhotorealTeacherReviewMappingError("review selection fields must match v1 exactly")
        coverage = _text(raw.get("coverage"), label="review selection coverage", maximum=64)
        if coverage in selected:
            raise PhotorealTeacherReviewMappingError("review selection repeats coverage")
        if coverage not in candidates:
            raise PhotorealTeacherReviewMappingError("review selection coverage is not required")
        orbit_index = raw.get("render_orbit_index")
        if isinstance(orbit_index, bool) or not isinstance(orbit_index, int) or orbit_index not in renders:
            raise PhotorealTeacherReviewMappingError("review selection render orbit index is invalid")
        observation_id = _sha(raw.get("reference_observation_id"), label="review reference observation id")
        if observation_id not in candidates[coverage]:
            raise PhotorealTeacherReviewMappingError("review reference observation is not a candidate for coverage")
        observation = observations[observation_id]
        source_key = _text(observation.get("source_key"), label="review observation source key")
        source = sources.get(source_key)
        if source is None:
            raise PhotorealTeacherReviewMappingError("review reference source is missing from catalog")
        render = renders[orbit_index]
        selected[coverage] = {
            "coverage": coverage,
            "render_orbit_index": orbit_index,
            "render_relative_path": render.get("relative_path"),
            "render_sha256": _sha(render.get("sha256"), label="selected render SHA-256"),
            "render_camera": render.get("camera"),
            "reference_observation_id": observation_id,
            "reference_source_key": source_key,
            "reference_source_resolved_path": source.get("resolved_path"),
            "reference_source_sha256": _sha(source.get("sha256"), label="selected reference source SHA-256"),
            "reference_frame_sha256": _sha(observation.get("frame_sha256"), label="selected reference frame SHA-256"),
            "reference_timestamp_seconds": observation.get("timestamp_seconds"),
            "reference_eye": observation.get("eye"),
            "reference_view_bin": observation.get("view_bin"),
            "reference_coverage": observation.get("coverage"),
            "reference_bytes_materialized": False,
            "reference_frame_hash_verified": False,
        }

    required = set(candidates)
    if set(selected) != required:
        missing = sorted(required - set(selected))
        extra = sorted(set(selected) - required)
        raise PhotorealTeacherReviewMappingError(
            f"review selection must cover required semantic views exactly (missing={missing}, extra={extra})"
        )

    mapping = [selected[label] for label in sorted(selected)]
    result: dict[str, Any] = {
        "format": OUTPUT_FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": epoch_id,
        "teacher_input_sha256": teacher_input_sha,
        "review_render_set_sha256": _sha(render_set.get("review_render_set_sha256"), label="review render set SHA-256"),
        "held_out_reference_catalog_sha256": _sha(
            reference_catalog.get("held_out_reference_catalog_sha256"), label="held-out reference catalog SHA-256"
        ),
        "reviewer": reviewer,
        "operator_supplied": True,
        "mapping_count": len(mapping),
        "mappings": mapping,
        "semantic_view_mapping_complete": True,
        "semantic_view_authority": "human-operator-mapping-v1",
        "reference_selection_complete": True,
        "reference_selection_authority": "human-operator-selection-v1",
        "reference_bytes_materialized": False,
        "reference_frame_hashes_verified": False,
        "likeness_review_complete": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["review_mapping_sha256"] = _digest(result, omit="review_mapping_sha256")
    return result


def build_review_mapping_files(
    render_set_path: str | Path,
    reference_catalog_path: str | Path,
    selection_input_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    render_set = _read_json(render_set_path, label="photoreal review render set")
    reference_catalog = _read_json(reference_catalog_path, label="photoreal held-out reference catalog")
    selection_input = _read_json(selection_input_path, label="photoreal review selection input")
    result = build_review_mapping(render_set, reference_catalog, selection_input)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherReviewMappingError(f"review mapping already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
