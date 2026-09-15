from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_frame_identity_authority import PhotorealFrameIdentityAuthorityError
from bodyrig.photoreal_frame_identity_integrity_authority import (
    authorize_frame_identity_files_integrity_checked,
)
from bodyrig.photoreal_identity_calibration import _canonical_calibration_digest
from bodyrig.photoreal_identity_calibration_integrity import (
    PhotorealIdentityCalibrationIntegrityError,
    validate_identity_calibration_integrity,
)
from bodyrig.photoreal_identity_calibration_provenance import (
    PhotorealIdentityCalibrationProvenanceError,
    bind_negative_inventory_provenance,
)


INVENTORY_SHA = "e" * 64


def _calibration() -> dict[str, object]:
    calibration: dict[str, object] = {
        "format": "bodyrig-photoreal-identity-calibration",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "d" * 64,
        "model_set_sha256": "c" * 64,
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "embedding_dimension": 32,
        "positive_reference_count": 4,
        "positive_group_count": 2,
        "negative_observation_count": 8,
        "negative_performer_count": 2,
        "positive_leave_group_out_cosine_min": 0.95,
        "positive_leave_group_out_cosine_median": 0.96,
        "positive_leave_group_out_cosine_max": 0.97,
        "negative_to_target_centroid_cosine_min": 0.10,
        "negative_to_target_centroid_cosine_median": 0.20,
        "negative_to_target_centroid_cosine_max": 0.30,
        "minimum_required_separation_margin": 0.05,
        "observed_separation_margin": 0.65,
        "threshold_derivation": "midpoint-positive-floor-negative-ceiling-v1",
        "identity_matching_authorized": True,
        "match_threshold_calibrated": True,
        "match_threshold": 0.625,
        "calibration_blockers": [],
        "calibration_data_teacher_input": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    calibration["identity_calibration_sha256"] = _canonical_calibration_digest(calibration)
    return calibration


def test_canonical_unbound_calibration_validates() -> None:
    calibration = _calibration()

    assert validate_identity_calibration_integrity(calibration) == calibration["identity_calibration_sha256"]


def test_inventory_bound_calibration_validates() -> None:
    calibration = bind_negative_inventory_provenance(_calibration(), INVENTORY_SHA)

    assert calibration["negative_inventory_sha256"] == INVENTORY_SHA
    assert validate_identity_calibration_integrity(calibration) == calibration["identity_calibration_sha256"]


def test_preseal_semantic_tamper_cannot_be_promoted() -> None:
    calibration = _calibration()
    calibration["match_threshold"] = 0.7

    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="core canonical digest mismatch"):
        bind_negative_inventory_provenance(calibration, INVENTORY_SHA)


def test_postseal_semantic_tamper_fails_closed() -> None:
    calibration = bind_negative_inventory_provenance(_calibration(), INVENTORY_SHA)
    calibration["match_threshold"] = 0.7

    with pytest.raises(PhotorealIdentityCalibrationIntegrityError, match="core canonical digest mismatch"):
        validate_identity_calibration_integrity(calibration)


def test_inventory_digest_tamper_fails_provenance_check() -> None:
    calibration = bind_negative_inventory_provenance(_calibration(), INVENTORY_SHA)
    calibration["negative_inventory_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationIntegrityError, match="provenance digest mismatch"):
        validate_identity_calibration_integrity(calibration)


def test_incomplete_provenance_pair_is_rejected() -> None:
    calibration = _calibration()
    calibration["negative_inventory_sha256"] = INVENTORY_SHA

    with pytest.raises(PhotorealIdentityCalibrationIntegrityError, match="binding is incomplete"):
        validate_identity_calibration_integrity(calibration)


def test_provenance_rebinding_is_rejected() -> None:
    calibration = bind_negative_inventory_provenance(_calibration(), INVENTORY_SHA)

    with pytest.raises(PhotorealIdentityCalibrationProvenanceError, match="already provenance-bound"):
        bind_negative_inventory_provenance(calibration, "f" * 64)


def test_frame_identity_file_boundary_rejects_tamper_before_core_use(tmp_path: Path) -> None:
    calibration = bind_negative_inventory_provenance(_calibration(), INVENTORY_SHA)
    calibration["negative_inventory_sha256"] = "f" * 64

    plan_path = tmp_path / "plan.json"
    measurements_path = tmp_path / "measurements.json"
    bank_path = tmp_path / "bank.json"
    calibration_path = tmp_path / "calibration.json"
    output_path = tmp_path / "authorized.json"
    for path in (plan_path, measurements_path, bank_path):
        path.write_text("{}\n", encoding="utf-8")
    calibration_path.write_text(json.dumps(calibration) + "\n", encoding="utf-8")

    with pytest.raises(PhotorealFrameIdentityAuthorityError, match="provenance digest mismatch"):
        authorize_frame_identity_files_integrity_checked(
            plan_path,
            measurements_path,
            bank_path,
            calibration_path,
            output_path,
        )

    assert not output_path.exists()
