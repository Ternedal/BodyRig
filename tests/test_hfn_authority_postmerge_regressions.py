from __future__ import annotations

import math

import pytest

import bodyrig.hands_feet_nails_landmark_evidence as evidence
import bodyrig.hands_feet_nails_source_capture as capture


HAND_LABELS = ("thumb", "index", "middle", "ring", "pinky")
FOOT_LABELS = ("big_toe", "small_toe", "heel")
LANDMARK_FIELDS = {"x_norm", "y_norm", "confidence"}
OLD_CAPTURE_POLICY = "bodyrig-hands-feet-nails-source-capture-v1"
EXPECTED_CAPTURE_POLICY = "bodyrig-hands-feet-nails-source-capture-exact-crop-v1"


def _landmark(x: float = 0.25, y: float = 0.50, confidence: float = 0.95) -> dict[str, float]:
    return {"x_norm": x, "y_norm": y, "confidence": confidence}


def _projection(region: str, *, complete: bool = True) -> dict:
    labels = list(HAND_LABELS if region.endswith("fingernails") else FOOT_LABELS)
    if not complete:
        labels = labels[:-1]
    landmarks = {
        label: _landmark(0.15 + index * 0.12, 0.30 + index * 0.05, 0.90 + index * 0.01)
        for index, label in enumerate(labels)
    }
    required = len(HAND_LABELS if region.endswith("fingernails") else FOOT_LABELS)
    return {
        "format": evidence.PROJECTION_FORMAT,
        "version": evidence.PROJECTION_VERSION,
        "policy_revision": evidence.PROJECTION_POLICY_REVISION,
        "region": region,
        "canvas_width": 1024,
        "canvas_height": 1024,
        "source_crop_px": [100, 50, 500, 450],
        "landmarks": landmarks,
        "required_landmark_count": required,
        "observed_landmark_count": len(landmarks),
        "application_ready": len(landmarks) == required,
        "source_coordinate_authority": "openpose-semantic-landmarks-explicit-crop",
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def _validate_projection(value: dict, *, region: str = "left_fingernails") -> dict:
    return evidence._validate_projection(
        value,
        semantic_region=region,
        crop_px=[100, 50, 500, 450],
    )


def test_source_capture_uses_exact_ffmpeg_crop_and_new_policy_boundary() -> None:
    filter_value = capture._ffmpeg_filter([0.10, 0.20, 0.40, 0.60])
    assert "exact=1" in filter_value
    assert capture.POLICY_REVISION == EXPECTED_CAPTURE_POLICY
    assert capture.POLICY_REVISION != OLD_CAPTURE_POLICY


def test_projection_accepts_canonical_full_and_incomplete_hand_semantics() -> None:
    full = _validate_projection(_projection("left_fingernails"))
    assert tuple(full["landmarks"]) == HAND_LABELS
    assert full["required_landmark_count"] == 5
    assert full["observed_landmark_count"] == 5
    assert full["application_ready"] is True

    partial = _validate_projection(_projection("left_fingernails", complete=False))
    assert set(partial["landmarks"]) == set(HAND_LABELS[:-1])
    assert partial["required_landmark_count"] == 5
    assert partial["observed_landmark_count"] == 4
    assert partial["application_ready"] is False


def test_projection_accepts_only_canonical_foot_semantics() -> None:
    full = _validate_projection(_projection("left_toenails"), region="left_toenails")
    assert tuple(full["landmarks"]) == FOOT_LABELS
    assert full["required_landmark_count"] == 3
    assert full["observed_landmark_count"] == 3
    assert full["application_ready"] is True


def test_projection_rejects_bogus_semantic_label_and_caller_controlled_required_count() -> None:
    bogus = _projection("left_fingernails")
    bogus["landmarks"] = dict(bogus["landmarks"])
    bogus["landmarks"].pop("pinky")
    bogus["landmarks"]["banana"] = _landmark()
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="semantic labels"):
        _validate_projection(bogus)

    forged_count = _projection("left_fingernails", complete=False)
    forged_count["required_landmark_count"] = 4
    forged_count["application_ready"] = True
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="required landmark count"):
        _validate_projection(forged_count)


def test_projection_rejects_noncanonical_landmark_fields() -> None:
    missing = _projection("left_fingernails")
    missing["landmarks"] = {name: dict(value) for name, value in missing["landmarks"].items()}
    missing["landmarks"]["thumb"].pop("confidence")
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="landmark fields"):
        _validate_projection(missing)

    extra = _projection("left_fingernails")
    extra["landmarks"] = {name: dict(value) for name, value in extra["landmarks"].items()}
    extra["landmarks"]["thumb"]["extra"] = 1
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="landmark fields"):
        _validate_projection(extra)


def test_projection_rejects_boolean_nonfinite_and_out_of_range_landmark_values() -> None:
    bad_values = (
        True,
        float("nan"),
        float("inf"),
        -0.0001,
        1.0001,
    )
    for field in LANDMARK_FIELDS:
        for bad in bad_values:
            value = _projection("left_fingernails")
            value["landmarks"] = {name: dict(item) for name, item in value["landmarks"].items()}
            value["landmarks"]["thumb"][field] = bad
            with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="landmark value"):
                _validate_projection(value)


def test_projection_rejects_forged_observed_count_or_readiness() -> None:
    bad_observed = _projection("left_fingernails")
    bad_observed["observed_landmark_count"] = 4
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="observed landmark count"):
        _validate_projection(bad_observed)

    bad_ready = _projection("left_fingernails", complete=False)
    bad_ready["application_ready"] = True
    with pytest.raises(evidence.HandsFeetNailsLandmarkEvidenceError, match="application readiness"):
        _validate_projection(bad_ready)
