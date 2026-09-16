from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_frame_analyzer_runner import (
    PhotorealFrameAnalyzerError,
    validate_analyzer_result,
)

MODEL_SET_SHA = "c" * 64


def _scan_plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "strategy": "uniform-midpoint-scout-v1",
        "sources": [
            {
                "source_key": "scene:s1:E:/source.mp4",
                "source_sha256": "a" * 64,
                "resolved_path": r"\\stash\VR_E\source.mp4",
                "kind": "video",
                "split": "train",
                "group_id": "scene:s1",
                "projection": "equi",
                "stereo_layout": "side-by-side",
                "decode_mode": "spatial-deprojection-required",
                "sample_count": 1,
                "samples": [{"timestamp_seconds": 1.25, "eye": "left"}],
            }
        ],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "frame_analyzer_required": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "test-analyzer",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": MODEL_SET_SHA,
        "identity_embedding_dimension": 32,
        "observations": [
            {
                "source_key": "scene:s1:E:/source.mp4",
                "source_sha256": "a" * 64,
                "kind": "video",
                "timestamp_seconds": 1.25,
                "eye": "left",
                "projection": "equi",
                "frame_sha256": "b" * 64,
                "perceptual_hash": "0123456789abcdef",
                "candidate_id": "v00-person-000",
                "person_detected": True,
                "width": 768,
                "height": 768,
                "view_bin": "front",
                "face_visibility": 0.9,
                "full_body_visibility": 0.9,
                "person_fraction": 0.8,
                "sharpness": 0.8,
                "motion": 0.0,
                "occlusion": 0.1,
                "identity_measurement_status": "available",
                "identity_embedding": [1.0] + [0.0] * 31,
            }
        ],
        "build_only": True,
        "production_activation": False,
    }


def _validate(result: dict[str, object], scan_plan: dict[str, object] | None = None) -> dict[str, object]:
    return validate_analyzer_result(
        result,
        performer_id="42",
        adapter="test-analyzer",
        revision="r1",
        model_set_sha256=MODEL_SET_SHA,
        scan_plan=_scan_plan() if scan_plan is None else scan_plan,
    )


def test_exact_scan_plan_source_and_sample_binding_passes() -> None:
    validated = _validate(_result())
    assert validated["observations"][0]["candidate_id"] == "v00-person-000"


def test_scan_binding_requires_exact_scan_plan() -> None:
    with pytest.raises(PhotorealFrameAnalyzerError, match="requires the exact scan plan"):
        validate_analyzer_result(
            _result(),
            performer_id="42",
            adapter="test-analyzer",
            revision="r1",
            model_set_sha256=MODEL_SET_SHA,
        )


def test_scan_binding_rejects_source_sha_mismatch() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["source_sha256"] = "d" * 64
    with pytest.raises(PhotorealFrameAnalyzerError, match="source SHA-256 differs"):
        _validate(result)


def test_scan_binding_rejects_projection_mismatch() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["projection"] = "cbmp"
    with pytest.raises(PhotorealFrameAnalyzerError, match="projection differs"):
        _validate(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestamp_seconds", 9.0),
        ("eye", "right"),
    ],
)
def test_scan_binding_rejects_unplanned_sample(field: str, value: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0][field] = value
    with pytest.raises(PhotorealFrameAnalyzerError, match="unplanned source sample"):
        _validate(result)


def test_scan_binding_requires_every_planned_sample_to_return_an_observation() -> None:
    scan = _scan_plan()
    source = scan["sources"][0]
    source["samples"] = [
        {"timestamp_seconds": 1.25, "eye": "left"},
        {"timestamp_seconds": 2.5, "eye": "left"},
    ]
    source["sample_count"] = 2
    with pytest.raises(PhotorealFrameAnalyzerError, match="exactly the planned sample set"):
        _validate(_result(), scan)


def test_scan_binding_rejects_boolean_scan_plan_version() -> None:
    scan = _scan_plan()
    scan["version"] = True
    with pytest.raises(PhotorealFrameAnalyzerError, match="scan plan format/version mismatch"):
        _validate(_result(), scan)


@pytest.mark.parametrize("timestamp", ["1.25", 10**400])
def test_scan_binding_rejects_non_schema_scan_plan_timestamp(timestamp: object) -> None:
    scan = _scan_plan()
    scan["sources"][0]["samples"][0]["timestamp_seconds"] = timestamp
    with pytest.raises(PhotorealFrameAnalyzerError, match="video frame sample timestamp"):
        _validate(_result(), scan)


@pytest.mark.parametrize("timestamp", ["1.25", 10**400])
def test_scan_binding_rejects_non_schema_result_timestamp(timestamp: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["timestamp_seconds"] = timestamp
    with pytest.raises(PhotorealFrameAnalyzerError, match="video frame sample timestamp"):
        _validate(result)


def test_scan_binding_allows_multiple_viewport_candidates_for_one_planned_sample() -> None:
    result = copy.deepcopy(_result())
    second = copy.deepcopy(result["observations"][0])
    second["candidate_id"] = "v01-person-000"
    second["frame_sha256"] = "e" * 64
    result["observations"].append(second)
    validated = _validate(result)
    assert [row["candidate_id"] for row in validated["observations"]] == [
        "v00-person-000",
        "v01-person-000",
    ]
