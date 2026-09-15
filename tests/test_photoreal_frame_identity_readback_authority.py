from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_frame_identity_readback_authority import (
    PhotorealFrameIdentityReadbackAuthorityError,
    authorize_frame_identity_files_strict,
    canonical_identity_bank_sha256,
    canonical_identity_calibration_sha256,
    validate_identity_matching_readback,
)


DIMENSION = 32
MODEL_SHA = "c" * 64
SOURCE_SHA = "a" * 64
FRAME_SHA = "b" * 64


def _embedding(x: float = 1.0, y: float = 0.0) -> list[float]:
    return [x, y] + [0.0] * (DIMENSION - 2)


def _reference(index: int, group: str) -> dict[str, object]:
    return {
        "source_key": f"scene:p42-{index}:E:/p42-{index}.mp4",
        "source_sha256": SOURCE_SHA,
        "group_id": group,
        "timestamp_seconds": float(index),
        "eye": "mono",
        "frame_sha256": f"{index}" * 64,
        "embedding": _embedding(),
    }


def _bank() -> dict[str, object]:
    references = [
        _reference(1, "g1"),
        _reference(2, "g1"),
        _reference(3, "g2"),
        _reference(4, "g2"),
    ]
    bank: dict[str, object] = {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "extractor": "insightface",
        "extractor_revision": "r1",
        "model_set_sha256": MODEL_SHA,
        "embedding_dimension": DIMENSION,
        "reference_count": len(references),
        "source_group_count": 2,
        "references": references,
        "centroid_embedding": _embedding(),
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
    }
    bank["identity_bank_sha256"] = canonical_identity_bank_sha256(bank)
    return bank


def _calibration(bank: dict[str, object]) -> dict[str, object]:
    calibration: dict[str, object] = {
        "format": "bodyrig-photoreal-identity-calibration",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "model_set_sha256": MODEL_SHA,
        "extractor": "insightface",
        "extractor_revision": "r1",
        "embedding_dimension": DIMENSION,
        "positive_reference_count": 4,
        "positive_group_count": 2,
        "negative_observation_count": 8,
        "negative_performer_count": 2,
        "positive_leave_group_out_cosine_min": 0.9,
        "positive_leave_group_out_cosine_median": 0.95,
        "positive_leave_group_out_cosine_max": 0.99,
        "negative_to_target_centroid_cosine_min": 0.1,
        "negative_to_target_centroid_cosine_median": 0.2,
        "negative_to_target_centroid_cosine_max": 0.3,
        "minimum_required_separation_margin": 0.05,
        "observed_separation_margin": 0.6,
        "threshold_derivation": "midpoint-positive-floor-negative-ceiling-v1",
        "match_threshold": 0.6,
        "match_threshold_calibrated": True,
        "identity_matching_authorized": True,
        "calibration_blockers": [],
        "calibration_data_teacher_input": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    calibration["identity_calibration_sha256"] = canonical_identity_calibration_sha256(calibration)
    return calibration


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "train": [
            {
                "source_id": "scene:single:E:/single.mp4",
                "performer_count": 1,
                "source_binding": "scene-performer",
            }
        ],
        "evaluation": [
            {
                "source_id": "image:gallery:F:/gallery.jpg",
                "performer_count": 0,
                "source_binding": "performer-gallery",
            }
        ],
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _measurements() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "frame-test",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": MODEL_SHA,
        "identity_embedding_dimension": DIMENSION,
        "observations": [
            {
                "source_key": "scene:single:E:/single.mp4",
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": FRAME_SHA,
                "candidate_id": "person-0",
                "person_detected": True,
                "identity_measurement_status": "unavailable",
                "identity_embedding": None,
            }
        ],
        "build_only": True,
        "production_activation": False,
    }


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_readback_accepts_canonical_bank_and_calibration() -> None:
    bank = _bank()
    dimension, centroid, threshold, authorized = validate_identity_matching_readback(bank, _calibration(bank))

    assert dimension == DIMENSION
    assert centroid[0] == 1.0
    assert threshold == 0.6
    assert authorized is True


def test_readback_rejects_bank_centroid_tamper_with_stale_digest() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    bank["centroid_embedding"] = _embedding(0.0, 1.0)

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="bank canonical digest mismatch"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_calibration_tamper_with_stale_digest() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    calibration["positive_leave_group_out_cosine_median"] = 0.94

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="calibration canonical digest mismatch"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_resealed_string_threshold() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    calibration["match_threshold"] = "0.6"
    calibration["identity_calibration_sha256"] = canonical_identity_calibration_sha256(calibration)

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="match threshold.*JSON number"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_resealed_authority_that_contradicts_evidence() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    calibration["negative_observation_count"] = 1
    calibration["identity_calibration_sha256"] = canonical_identity_calibration_sha256(calibration)

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="authority contradicts calibration evidence"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_resealed_wrong_threshold_derivation_result() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    calibration["match_threshold"] = 0.7
    calibration["identity_calibration_sha256"] = canonical_identity_calibration_sha256(calibration)

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="threshold contradicts calibration evidence"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_boolean_calibration_version() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    calibration["version"] = True
    calibration["identity_calibration_sha256"] = canonical_identity_calibration_sha256(calibration)

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="calibration format/version mismatch"):
        validate_identity_matching_readback(bank, calibration)


def test_readback_rejects_boolean_zero_bank_count_even_when_digest_unchanged() -> None:
    bank = _bank()
    calibration = _calibration(bank)
    bank["evaluation_reference_count"] = False

    with pytest.raises(PhotorealFrameIdentityReadbackAuthorityError, match="evaluation reference count.*JSON integer"):
        validate_identity_matching_readback(bank, calibration)


def test_strict_file_authority_delegates_only_after_readback(tmp_path: Path) -> None:
    bank = _bank()
    calibration = _calibration(bank)
    plan_path = tmp_path / "plan.json"
    measurements_path = tmp_path / "measurements.json"
    bank_path = tmp_path / "bank.json"
    calibration_path = tmp_path / "calibration.json"
    output_path = tmp_path / "authorized.json"
    _write(plan_path, _plan())
    _write(measurements_path, _measurements())
    _write(bank_path, bank)
    _write(calibration_path, calibration)

    result = authorize_frame_identity_files_strict(
        plan_path,
        measurements_path,
        bank_path,
        calibration_path,
        output_path,
    )

    assert output_path.is_file()
    assert result["identity_matching_calibrated"] is True
    assert result["identity_match_threshold"] == 0.6
    assert result["observations"][0]["target_identity_verified"] is True
