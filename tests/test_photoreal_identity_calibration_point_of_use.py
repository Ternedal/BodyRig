from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_calibration_authority import (
    PhotorealIdentityCalibrationAuthorityError,
    validate_calibration_point_of_use_types,
)


DIMENSION = 32
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _embedding(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIMENSION - 1)


def _reference(index: int, group: str) -> dict[str, object]:
    return {
        "source_key": f"scene:s{index}:E:/p42-{index}.mp4",
        "source_sha256": SHA_A,
        "group_id": group,
        "timestamp_seconds": float(index),
        "eye": "mono",
        "frame_sha256": SHA_B,
        "embedding": _embedding(1.0),
    }


def _bank() -> dict[str, object]:
    references = [
        _reference(1, "g1"),
        _reference(2, "g1"),
        _reference(3, "g2"),
        _reference(4, "g2"),
    ]
    return {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "extractor": "insightface",
        "extractor_revision": "r1",
        "model_set_sha256": SHA_C,
        "embedding_dimension": DIMENSION,
        "reference_count": len(references),
        "source_group_count": 2,
        "references": references,
        "centroid_embedding": _embedding(1.0),
        "reference_to_centroid_cosine_min": 1.0,
        "reference_to_centroid_cosine_median": 1.0,
        "reference_to_centroid_cosine_max": 1.0,
        "train_only": True,
        "evaluation_reference_count": 0,
        "match_threshold_calibrated": False,
        "identity_matching_authorized": False,
        "identity_bank_ready_for_calibration": True,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
        "identity_bank_sha256": SHA_D,
    }


def _source(index: int, subject: str) -> dict[str, object]:
    return {
        "source_key": f"scene:n{index}:E:/negative-{index}.mp4",
        "source_sha256": SHA_A,
        "resolved_path": f"E:/negative-{index}.mp4",
        "subject_performer_id": subject,
        "subject_performer_name": f"Negative {subject}",
        "target_performer_id": "42",
        "target_performer_absent": True,
        "label_authority": "stash-single-performer-other-id-v1",
        "kind": "video",
        "source_binding": "scene-single-performer",
        "projection": "equirectangular",
        "stereo_layout": "mono",
        "decode_mode": "video",
        "sample_count": 1,
        "samples": [{"timestamp_seconds": float(index), "eye": "mono"}],
    }


def _plan() -> dict[str, object]:
    sources = [_source(1, "7"), _source(2, "8")]
    return {
        "format": "bodyrig-photoreal-identity-calibration-plan",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": SHA_D,
        "negative_inventory_sha256": SHA_B,
        "model_set_sha256": SHA_C,
        "extractor": "insightface",
        "extractor_revision": "r1",
        "embedding_dimension": DIMENSION,
        "label_authority": "stash-single-performer-other-id-v1",
        "negative_performer_count": 2,
        "source_count": len(sources),
        "planned_negative_observation_count": 2,
        "video_timestamps_per_source": 6,
        "sources": sources,
        "negative_embedding_extraction_required": True,
        "calibration_only": True,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observations() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": SHA_D,
        "extractor": "insightface",
        "extractor_revision": "r1",
        "model_set_sha256": SHA_C,
        "embedding_dimension": DIMENSION,
        "observations": [
            {
                "source_key": "scene:n1:E:/negative-1.mp4",
                "source_sha256": SHA_A,
                "subject_performer_id": "7",
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": SHA_B,
                "embedding": _embedding(0.5),
            }
        ],
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def test_point_of_use_accepts_canonical_json_types() -> None:
    validate_calibration_point_of_use_types(_bank(), _plan(), _observations())


def test_point_of_use_rejects_boolean_bank_version() -> None:
    bank = _bank()
    bank["version"] = True

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="bank version.*JSON integer"):
        validate_calibration_point_of_use_types(bank, _plan(), _observations())


def test_point_of_use_rejects_boolean_zero_count_confusion() -> None:
    bank = _bank()
    bank["evaluation_reference_count"] = False

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="evaluation reference count.*JSON integer"):
        validate_calibration_point_of_use_types(bank, _plan(), _observations())


def test_point_of_use_rejects_string_plan_dimension() -> None:
    plan = _plan()
    plan["embedding_dimension"] = "32"

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="plan embedding dimension.*JSON integer"):
        validate_calibration_point_of_use_types(_bank(), plan, _observations())


def test_point_of_use_rejects_string_plan_timestamp() -> None:
    plan = copy.deepcopy(_plan())
    plan["sources"][0]["samples"][0]["timestamp_seconds"] = "1.0"

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="timestamp.*JSON number"):
        validate_calibration_point_of_use_types(_bank(), plan, _observations())


def test_point_of_use_rejects_non_string_observation_performer() -> None:
    observations = copy.deepcopy(_observations())
    observations["target_performer_id"] = 42

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="target performer.*JSON string"):
        validate_calibration_point_of_use_types(_bank(), _plan(), observations)


def test_point_of_use_rejects_numeric_string_embedding_component() -> None:
    observations = copy.deepcopy(_observations())
    observations["observations"][0]["embedding"][0] = "0.5"

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="embedding\[0\].*JSON number"):
        validate_calibration_point_of_use_types(_bank(), _plan(), observations)
