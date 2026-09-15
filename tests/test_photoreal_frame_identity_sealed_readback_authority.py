from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_frame_identity_readback_authority import (
    canonical_identity_bank_sha256,
    canonical_identity_calibration_sha256,
)
from bodyrig.photoreal_frame_identity_sealed_readback_authority import (
    PhotorealFrameIdentitySealedReadbackAuthorityError,
    validate_sealed_identity_matching_readback,
)
from bodyrig.photoreal_identity_calibration_authority import bind_negative_inventory_provenance


DIMENSION = 32
MODEL_SHA = "c" * 64
NEGATIVE_INVENTORY_SHA = "f" * 64


def _embedding(x: float = 1.0, y: float = 0.0) -> list[float]:
    return [x, y] + [0.0] * (DIMENSION - 2)


def _reference(index: int, group: str) -> dict[str, object]:
    return {
        "source_key": f"scene:p42-{index}:E:/p42-{index}.mp4",
        "source_sha256": "a" * 64,
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
        "reference_count": 4,
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


def _calibration_core(bank: dict[str, object], *, threshold: float = 0.6) -> dict[str, object]:
    core: dict[str, object] = {
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
        "match_threshold": threshold,
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
    core["identity_calibration_sha256"] = canonical_identity_calibration_sha256(core)
    return core


def _sealed_calibration(bank: dict[str, object], *, threshold: float = 0.6) -> dict[str, object]:
    return bind_negative_inventory_provenance(
        _calibration_core(bank, threshold=threshold),
        NEGATIVE_INVENTORY_SHA,
    )


def test_sealed_readback_accepts_inventory_bound_calibration() -> None:
    bank = _bank()

    dimension, centroid, threshold, authorized = validate_sealed_identity_matching_readback(
        bank,
        _sealed_calibration(bank),
    )

    assert dimension == DIMENSION
    assert centroid[0] == 1.0
    assert threshold == 0.6
    assert authorized is True


def test_sealed_readback_rejects_bank_centroid_tamper() -> None:
    bank = _bank()
    calibration = _sealed_calibration(bank)
    bank["centroid_embedding"] = _embedding(0.0, 1.0)

    with pytest.raises(PhotorealFrameIdentitySealedReadbackAuthorityError, match="bank canonical digest mismatch"):
        validate_sealed_identity_matching_readback(bank, calibration)


def test_sealed_readback_rejects_outer_calibration_seal_tamper() -> None:
    bank = _bank()
    calibration = copy.deepcopy(_sealed_calibration(bank))
    calibration["identity_calibration_sha256"] = "0" * 64

    with pytest.raises(PhotorealFrameIdentitySealedReadbackAuthorityError, match="provenance digest mismatch"):
        validate_sealed_identity_matching_readback(bank, calibration)


def test_sealed_readback_rejects_validly_resealed_wrong_threshold() -> None:
    bank = _bank()
    calibration = _sealed_calibration(bank, threshold=0.7)

    with pytest.raises(PhotorealFrameIdentitySealedReadbackAuthorityError, match="threshold contradicts calibration evidence"):
        validate_sealed_identity_matching_readback(bank, calibration)
