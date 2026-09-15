from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

RENDER_SET_FORMAT = "bodyrig-photoreal-teacher-review-render-set"
MAPPING_FORMAT = "bodyrig-photoreal-teacher-review-mapping"
MATERIALIZATION_FORMAT = "bodyrig-photoreal-reference-frame-materialization-receipt"
INPUT_FORMAT = "bodyrig-photoreal-static-teacher-human-review-input"
FORMAT = "bodyrig-photoreal-static-teacher-human-review"
VERSION = 1
CHECKS = {
    "identity_likeness",
    "skin_material_not_waxy_or_plastic",
    "eyes_source_consistent",
    "hair_silhouette_source_consistent",
    "hands_anatomically_credible",
    "cross_view_geometry_and_identity_stable",
}


class PhotorealStaticTeacherReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealStaticTeacherReviewError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealStaticTeacherReviewError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PhotorealStaticTeacherReviewError(f"{label} is invalid")
    clean = value.strip()
    if (not clean and not allow_empty) or len(value) > maximum:
        raise PhotorealStaticTeacherReviewError(f"{label} is invalid")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealStaticTeacherReviewError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealStaticTeacherReviewError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value != 1:
        raise PhotorealStaticTeacherReviewError(f"{label} version must be numeric v1")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _safe_file(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    value = _text(relative, label=label, maximum=4096).replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealStaticTeacherReviewError(f"{label} escapes its review root")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealStaticTeacherReviewError(f"{label} escapes its review root") from exc
    if not path.is_file():
        raise PhotorealStaticTeacherReviewError(f"{label} is missing: {value}")
    return value, path


def _validate_render_set(value: Mapping[str, Any]) -> tuple[str, str, str, str, dict[int, Mapping[str, Any]]]:
    if value.get("format") != RENDER_SET_FORMAT:
        raise PhotorealStaticTeacherReviewError("review render set format mismatch")
    _v1(value.get("version"), label="review render set")
    digest = _sha(value.get("review_render_set_sha256"), label="review render set SHA-256")
    if _digest(value, omit="review_render_set_sha256") != digest:
        raise PhotorealStaticTeacherReviewError("review render set digest mismatch")
    if value.get("render_bytes_verified") is not True or value.get("camera_geometry_authority") is not True:
        raise PhotorealStaticTeacherReviewError("review render set lacks byte/camera authority")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealStaticTeacherReviewError("review render set crossed downstream authority")
    raw_renders = value.get("renders")
    if not isinstance(raw_renders, list) or len(raw_renders) != 50:
        raise PhotorealStaticTeacherReviewError("review render set must contain 50 renders")
    renders: dict[int, Mapping[str, Any]] = {}
    for raw in raw_renders:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("camera"), Mapping):
            raise PhotorealStaticTeacherReviewError("review render entry is invalid")
        index = raw["camera"].get("orbit_index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 50 or index in renders:
            raise PhotorealStaticTeacherReviewError("review render orbit authority is invalid")
        renders[index] = raw
    return (
        _text(value.get("performer_id"), label="render performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="render epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="render teacher input SHA-256"),
        digest,
        renders,
    )


def _validate_mapping(value: Mapping[str, Any]) -> tuple[str, str, str, str, str, list[Mapping[str, Any]]]:
    if value.get("format") != MAPPING_FORMAT:
        raise PhotorealStaticTeacherReviewError("review mapping format mismatch")
    _v1(value.get("version"), label="review mapping")
    digest = _sha(value.get("review_mapping_sha256"), label="review mapping SHA-256")
    if _digest(value, omit="review_mapping_sha256") != digest:
        raise PhotorealStaticTeacherReviewError("review mapping digest mismatch")
    if value.get("semantic_view_mapping_complete") is not True or value.get("reference_selection_complete") is not True:
        raise PhotorealStaticTeacherReviewError("review mapping is incomplete")
    if value.get("reference_bytes_materialized") is not False or value.get("likeness_review_complete") is not False:
        raise PhotorealStaticTeacherReviewError("review mapping already crossed the pre-review boundary")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealStaticTeacherReviewError("review mapping crossed downstream authority")
    mappings = value.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise PhotorealStaticTeacherReviewError("review mapping contains no mappings")
    return (
        _text(value.get("performer_id"), label="mapping performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="mapping epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="mapping teacher input SHA-256"),
        _sha(value.get("review_render_set_sha256"), label="mapping render set SHA-256"),
        digest,
        mappings,
    )


def _validate_materialization(value: Mapping[str, Any]) -> tuple[str, str, str, str, str, list[Mapping[str, Any]]]:
    if value.get("format") != MATERIALIZATION_FORMAT:
        raise PhotorealStaticTeacherReviewError("reference materialization receipt format mismatch")
    _v1(value.get("version"), label="reference materialization receipt")
    if value.get("all_source_hashes_verified") is not True or value.get("all_frame_hashes_verified") is not True:
        raise PhotorealStaticTeacherReviewError("reference materialization lacks source/frame proof")
    if value.get("photoreal_acceptance_authority") is not False or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealStaticTeacherReviewError("reference materialization crossed photoreal/human authority")
    if value.get("production_activation") is not False:
        raise PhotorealStaticTeacherReviewError("reference materialization crossed production authority")
    refs = value.get("materialized_references")
    if not isinstance(refs, list) or not refs:
        raise PhotorealStaticTeacherReviewError("reference materialization contains no references")
    return (
        _text(value.get("performer_id"), label="materialization performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="materialization epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="materialization teacher input SHA-256"),
        _sha(value.get("review_mapping_sha256"), label="materialization mapping SHA-256"),
        _sha(value.get("held_out_reference_catalog_sha256"), label="materialization catalog SHA-256"),
        refs,
    )


def _validate_human_input(value: Mapping[str, Any], *, required_coverages: set[str]) -> tuple[str, dict[str, str], dict[str, str], str, str]:
    required = {"format", "version", "reviewer", "operator_supplied", "coverage_reviews", "checklist", "overall_decision", "quality_note"}
    if set(value) != required:
        raise PhotorealStaticTeacherReviewError("human review input fields must match v1 exactly")
    if value.get("format") != INPUT_FORMAT:
        raise PhotorealStaticTeacherReviewError("human review input format mismatch")
    _v1(value.get("version"), label="human review input")
    reviewer = _text(value.get("reviewer"), label="human reviewer", maximum=256)
    if value.get("operator_supplied") is not True:
        raise PhotorealStaticTeacherReviewError("human review input must be explicitly operator supplied")
    coverage_raw = value.get("coverage_reviews")
    if not isinstance(coverage_raw, list) or not coverage_raw:
        raise PhotorealStaticTeacherReviewError("human review input has no coverage reviews")
    coverage_reviews: dict[str, str] = {}
    for raw in coverage_raw:
        if not isinstance(raw, Mapping) or set(raw) != {"coverage", "outcome"}:
            raise PhotorealStaticTeacherReviewError("coverage review fields must match v1 exactly")
        coverage = _text(raw.get("coverage"), label="coverage review", maximum=64)
        outcome = raw.get("outcome")
        if outcome not in {"pass", "fail"}:
            raise PhotorealStaticTeacherReviewError("coverage review outcome must be pass or fail")
        if coverage in coverage_reviews:
            raise PhotorealStaticTeacherReviewError("human review input repeats coverage")
        coverage_reviews[coverage] = str(outcome)
    if set(coverage_reviews) != required_coverages:
        raise PhotorealStaticTeacherReviewError("human review must cover the mapped semantic-view universe exactly")

    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKS:
        raise PhotorealStaticTeacherReviewError("human review checklist fields are not canonical")
    checklist_outcomes: dict[str, str] = {}
    for key in sorted(CHECKS):
        outcome = checklist.get(key)
        if outcome not in {"pass", "fail"}:
            raise PhotorealStaticTeacherReviewError(f"human review checklist outcome is invalid: {key}")
        checklist_outcomes[key] = str(outcome)
    overall = value.get("overall_decision")
    if overall not in {"pass", "fail"}:
        raise PhotorealStaticTeacherReviewError("overall human review decision must be pass or fail")
    expected_pass = all(item == "pass" for item in coverage_reviews.values()) and all(item == "pass" for item in checklist_outcomes.values())
    if (overall == "pass") != expected_pass:
        raise PhotorealStaticTeacherReviewError("overall human review decision contradicts detailed outcomes")
    quality_note = _text(value.get("quality_note"), label="human review quality note", maximum=4000)
    return reviewer, coverage_reviews, checklist_outcomes, str(overall), quality_note


def finalize_static_teacher_review(
    render_set: Mapping[str, Any],
    mapping: Mapping[str, Any],
    materialization: Mapping[str, Any],
    human_input: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    reference_output_root: str | Path,
    materialization_receipt_sha256: str,
) -> dict[str, Any]:
    performer, epoch, teacher_input_sha, render_set_sha, renders = _validate_render_set(render_set)
    m_performer, m_epoch, m_teacher_sha, m_render_sha, mapping_sha, mappings = _validate_mapping(mapping)
    r_performer, r_epoch, r_teacher_sha, r_mapping_sha, catalog_sha, materialized = _validate_materialization(materialization)
    if (m_performer, m_epoch, m_teacher_sha) != (performer, epoch, teacher_input_sha):
        raise PhotorealStaticTeacherReviewError("render/mapping lineage mismatch")
    if (r_performer, r_epoch, r_teacher_sha) != (performer, epoch, teacher_input_sha):
        raise PhotorealStaticTeacherReviewError("render/materialization lineage mismatch")
    if m_render_sha != render_set_sha or r_mapping_sha != mapping_sha:
        raise PhotorealStaticTeacherReviewError("review evidence digest lineage mismatch")

    refs: dict[str, Mapping[str, Any]] = {}
    for raw in materialized:
        if not isinstance(raw, Mapping):
            raise PhotorealStaticTeacherReviewError("materialized reference entry is invalid")
        observation_id = _sha(raw.get("observation_id"), label="materialized observation id")
        if observation_id in refs:
            raise PhotorealStaticTeacherReviewError("materialization repeats observation id")
        if raw.get("source_hash_verified") is not True or raw.get("frame_hash_verified") is not True:
            raise PhotorealStaticTeacherReviewError("materialized reference lacks hash proof")
        if raw.get("expected_frame_sha256") != raw.get("observed_frame_sha256"):
            raise PhotorealStaticTeacherReviewError("materialized reference frame hashes diverge")
        refs[observation_id] = raw

    mapping_by_coverage: dict[str, Mapping[str, Any]] = {}
    for raw in mappings:
        if not isinstance(raw, Mapping):
            raise PhotorealStaticTeacherReviewError("review mapping entry is invalid")
        coverage = _text(raw.get("coverage"), label="mapped coverage", maximum=64)
        if coverage in mapping_by_coverage:
            raise PhotorealStaticTeacherReviewError("review mapping repeats coverage")
        mapping_by_coverage[coverage] = raw
    reviewer, coverage_reviews, checklist, overall, quality_note = _validate_human_input(
        human_input, required_coverages=set(mapping_by_coverage)
    )

    teacher_root = Path(teacher_output_root).expanduser().resolve()
    reference_root = Path(reference_output_root).expanduser().resolve()
    comparisons: list[dict[str, Any]] = []
    for coverage in sorted(mapping_by_coverage):
        item = mapping_by_coverage[coverage]
        orbit = item.get("render_orbit_index")
        if isinstance(orbit, bool) or not isinstance(orbit, int) or orbit not in renders:
            raise PhotorealStaticTeacherReviewError("mapped teacher render orbit is invalid")
        render = renders[orbit]
        if item.get("render_relative_path") != render.get("relative_path") or item.get("render_sha256") != render.get("sha256"):
            raise PhotorealStaticTeacherReviewError("mapping no longer matches exact teacher render authority")
        render_relative, render_path = _safe_file(teacher_root, item.get("render_relative_path"), label="teacher render")
        render_sha = _sha(item.get("render_sha256"), label="teacher render SHA-256")
        if _hash_file(render_path) != render_sha:
            raise PhotorealStaticTeacherReviewError(f"teacher render bytes drifted: {render_relative}")

        observation_id = _sha(item.get("reference_observation_id"), label="reference observation id")
        reference = refs.get(observation_id)
        if reference is None:
            raise PhotorealStaticTeacherReviewError("mapped reference observation was not materialized")
        coverages = reference.get("coverages")
        if not isinstance(coverages, list) or coverage not in coverages:
            raise PhotorealStaticTeacherReviewError("materialized reference is not authorized for mapped coverage")
        if item.get("reference_frame_sha256") != reference.get("observed_frame_sha256"):
            raise PhotorealStaticTeacherReviewError("mapping/materialized frame authority mismatch")
        reference_relative, reference_path = _safe_file(reference_root, reference.get("png_relative_path"), label="held-out reference PNG")
        reference_png_sha = _sha(reference.get("png_sha256"), label="held-out reference PNG SHA-256")
        if _hash_file(reference_path) != reference_png_sha:
            raise PhotorealStaticTeacherReviewError(f"held-out reference PNG bytes drifted: {reference_relative}")
        comparisons.append({
            "coverage": coverage,
            "teacher_render_orbit_index": orbit,
            "teacher_render_relative_path": render_relative,
            "teacher_render_sha256": render_sha,
            "reference_observation_id": observation_id,
            "reference_png_relative_path": reference_relative,
            "reference_png_sha256": reference_png_sha,
            "reference_frame_sha256": _sha(reference.get("observed_frame_sha256"), label="reference frame SHA-256"),
            "human_outcome": coverage_reviews[coverage],
        })

    passed = overall == "pass"
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer,
        "selected_epoch_id": epoch,
        "teacher_input_sha256": teacher_input_sha,
        "review_render_set_sha256": render_set_sha,
        "review_mapping_sha256": mapping_sha,
        "held_out_reference_catalog_sha256": catalog_sha,
        "materialization_receipt_sha256": _sha(materialization_receipt_sha256, label="materialization receipt SHA-256"),
        "reviewer": reviewer,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "operator_supplied": True,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "checklist": checklist,
        "quality_note": quality_note,
        "human_review_complete": True,
        "human_review_outcome": overall,
        "human_review_pass": passed,
        "static_teacher_photoreal_accepted": passed,
        "photoreal_acceptance_authority": passed,
        "p2_animation_work_authorized": passed,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["static_teacher_review_sha256"] = _digest(result, omit="static_teacher_review_sha256")
    return result


def finalize_static_teacher_review_files(
    render_set_path: str | Path,
    mapping_path: str | Path,
    materialization_receipt_path: str | Path,
    human_input_path: str | Path,
    teacher_output_root: str | Path,
    reference_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    materialization_path = Path(materialization_receipt_path).expanduser().resolve()
    render_set = _read_json(render_set_path, label="photoreal review render set")
    mapping = _read_json(mapping_path, label="photoreal review mapping")
    materialization = _read_json(materialization_path, label="photoreal reference materialization receipt")
    human_input = _read_json(human_input_path, label="photoreal static teacher human review input")
    result = finalize_static_teacher_review(
        render_set,
        mapping,
        materialization,
        human_input,
        teacher_output_root=teacher_output_root,
        reference_output_root=reference_output_root,
        materialization_receipt_sha256=_hash_file(materialization_path),
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealStaticTeacherReviewError(f"static teacher review already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise PhotorealStaticTeacherReviewError(f"refusing to overwrite static teacher review: {output}") from exc
    return result
