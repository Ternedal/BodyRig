from __future__ import annotations

import math

import pytest

from bodyrig.photoreal_identity_representation_outlier import (
    PhotorealIdentityRepresentationOutlierError,
    analyze,
)


def _bank() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "identity_bank_sha256": "a" * 64,
        "embedding_dimension": 3,
        "references": [
            {
                "group_id": "scene:1",
                "frame_sha256": "1" * 64,
                "eye": "left",
                "embedding": [1.0, 0.0, 0.0],
            },
            {
                "group_id": "scene:1",
                "frame_sha256": "2" * 64,
                "eye": "right",
                "embedding": [0.98, 0.2, 0.0],
            },
            {
                "group_id": "scene:2",
                "frame_sha256": "3" * 64,
                "eye": "left",
                "embedding": [0.96, 0.28, 0.0],
            },
            {
                "group_id": "scene:2",
                "frame_sha256": "4" * 64,
                "eye": "right",
                "embedding": [0.1, 0.995, 0.0],
            },
        ],
    }


def _quality(face_px: float, det: float, yaw: float) -> dict[str, object]:
    return {
        "bbox_min_dimension_pixels": face_px,
        "det_score": det,
        "face_crop_sharpness": 0.8,
        "frame_sharpness": 0.7,
        "face_center_offset_fraction": 0.1,
        "pose": {
            "yaw_degrees": yaw,
            "pitch_degrees": 3.0,
            "roll_degrees": 2.0,
        },
    }


def _diagnostic() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-representation-diagnostic",
        "version": 1,
        "performer_id": "42",
        "identity_bank_sha256": "a" * 64,
        "reference_count": 4,
        "human_attested_group_count": 2,
        "diagnostic_only": True,
        "identity_group_selection_authority": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "diagnostic_bodyrig_revision": "b" * 40,
        "references": [
            {
                "reference_index": 0,
                "group_id": "scene:1",
                "frame_sha256": "1" * 64,
                "eye": "left",
                "timestamp_seconds": 1.0,
                "current_profile_cosine": 0.5,
                "current_quality": _quality(140.0, 0.9, 5.0),
                "centered_variants": {
                    "face-centered-90": {
                        "status": "available",
                        "to_bank_reference_cosine": 0.95,
                    }
                },
            },
            {
                "reference_index": 1,
                "group_id": "scene:1",
                "frame_sha256": "2" * 64,
                "eye": "right",
                "timestamp_seconds": 1.0,
                "current_profile_cosine": 0.45,
                "current_quality": _quality(120.0, 0.85, 10.0),
                "centered_variants": {
                    "face-centered-90": {
                        "status": "available",
                        "to_bank_reference_cosine": 0.94,
                    }
                },
            },
            {
                "reference_index": 2,
                "group_id": "scene:2",
                "frame_sha256": "3" * 64,
                "eye": "left",
                "timestamp_seconds": 2.0,
                "current_profile_cosine": 0.4,
                "current_quality": _quality(100.0, 0.8, 20.0),
                "centered_variants": {
                    "face-centered-90": {
                        "status": "multiple-person-candidates",
                    }
                },
            },
            {
                "reference_index": 3,
                "group_id": "scene:2",
                "frame_sha256": "4" * 64,
                "eye": "right",
                "timestamp_seconds": 2.0,
                "current_profile_cosine": 0.1,
                "current_quality": _quality(40.0, 0.55, 65.0),
                "centered_variants": {
                    "face-centered-90": {
                        "status": "no-person-candidates",
                    }
                },
            },
        ],
        "stereo_pairs": [
            {
                "source_key_sha256": "c" * 64,
                "timestamp_seconds": 1.0,
                "variant_cosines": {
                    "bank-original": 0.98,
                    "face-centered-90": 0.96,
                },
            }
        ],
    }


def test_outlier_analysis_surfaces_weak_reference_and_variant_failures() -> None:
    result = analyze(_bank(), _diagnostic(), worst_count=4)

    assert result["reference_count"] == 4
    assert result["group_count"] == 2
    assert result["baseline_leave_group_out"]["min"] < 0.5
    assert result["worst_references"][0]["reference_index"] == 3
    assert result["worst_references"][0]["group_id"] == "scene:2"
    assert result["centered_status_counts"]["face-centered-90"] == {
        "available": 2,
        "multiple-person-candidates": 1,
        "no-person-candidates": 1,
    }
    assert result["centered_to_bank_cosine"]["face-centered-90"]["count"] == 2
    assert result["stereo_pair_cosine"]["bank-original"]["median"] == 0.98
    assert result["diagnostic_only"] is True
    assert result["identity_matching_authorized"] is False
    assert result["production_activation"] is False


def test_outlier_analysis_quality_correlation_detects_size_signal() -> None:
    result = analyze(_bank(), _diagnostic(), worst_count=4)

    value = result["quality_correlations"]["face_min_dimension_pixels"][
        "vs_leave_group_out"
    ]["spearman"]
    assert value is not None
    assert math.isfinite(value)


def test_outlier_analysis_rejects_reference_binding_drift() -> None:
    diagnostic = _diagnostic()
    diagnostic["references"][0]["frame_sha256"] = "f" * 64

    with pytest.raises(
        PhotorealIdentityRepresentationOutlierError,
        match="reference binding mismatch",
    ):
        analyze(_bank(), diagnostic)


def test_outlier_analysis_rejects_human_attested_group_count_drift() -> None:
    diagnostic = _diagnostic()
    diagnostic["human_attested_group_count"] = 1

    with pytest.raises(
        PhotorealIdentityRepresentationOutlierError,
        match="human-attested group count mismatch",
    ):
        analyze(_bank(), diagnostic)
