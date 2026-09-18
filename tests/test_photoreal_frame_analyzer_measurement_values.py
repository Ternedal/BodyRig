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
                "full_body_visibility": 0.8,
                "person_fraction": 0.7,
                "sharpness": 0.6,
                "motion": 0.0,
                "occlusion": 0.1,
                "identity_measurement_status": "available",
                "identity_embedding": [1.0] + [0.0] * 31,
            }
        ],
        "build_only": True,
        "production_activation": False,
    }


def _validate(result: dict[str, object]) -> dict[str, object]:
    return validate_analyzer_result(
        result,
        performer_id="42",
        adapter="test-analyzer",
        revision="r1",
        model_set_sha256=MODEL_SET_SHA,
        scan_plan=_scan_plan(),
    )


def test_measurement_value_contract_accepts_reference_shape() -> None:
    validated = _validate(_result())
    assert validated["observations"][0]["view_bin"] == "front"


@pytest.mark.parametrize(
    ("field", "value"),
    [("width", 0), ("width", True), ("height", 0), ("height", False)],
)
def test_measurement_value_contract_rejects_invalid_dimensions(field: str, value: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0][field] = value
    with pytest.raises(PhotorealFrameAnalyzerError, match=field):
        _validate(result)


@pytest.mark.parametrize(
    "value",
    ["0123456789abcde", "0123456789ABCDEG", 1234567890123456],
)
def test_measurement_value_contract_rejects_noncanonical_perceptual_hash(value: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["perceptual_hash"] = value
    with pytest.raises(PhotorealFrameAnalyzerError, match="perceptual_hash"):
        _validate(result)


def test_measurement_value_contract_accepts_rear_view_bin() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["view_bin"] = "rear"
    validated = _validate(result)
    assert validated["observations"][0]["view_bin"] == "rear"


def test_measurement_value_contract_rejects_unknown_view_bin() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["view_bin"] = "overhead"
    with pytest.raises(PhotorealFrameAnalyzerError, match="view_bin"):
        _validate(result)


def test_measurement_value_contract_rejects_unknown_observation_field() -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["unexpected_extension"] = True
    with pytest.raises(PhotorealFrameAnalyzerError, match="unsupported fields"):
        _validate(result)


def test_measurement_value_contract_enforces_schema_observation_limit() -> None:
    result = _result()
    row = result["observations"][0]
    result["observations"] = [row] * 250_001
    with pytest.raises(PhotorealFrameAnalyzerError, match="too many observations"):
        _validate(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("face_visibility", 1.01),
        ("full_body_visibility", -0.01),
        ("person_fraction", float("nan")),
        ("sharpness", float("inf")),
        ("motion", True),
        ("occlusion", "0.1"),
        ("occlusion", 10**400),
    ],
)
def test_measurement_value_contract_rejects_invalid_unit_metrics(field: str, value: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0][field] = value
    with pytest.raises(PhotorealFrameAnalyzerError, match=field):
        _validate(result)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.0", 10**400])
def test_measurement_value_contract_rejects_invalid_embedding_components(value: object) -> None:
    result = copy.deepcopy(_result())
    result["observations"][0]["identity_embedding"][1] = value
    with pytest.raises(PhotorealFrameAnalyzerError, match="identity embedding component"):
        _validate(result)
