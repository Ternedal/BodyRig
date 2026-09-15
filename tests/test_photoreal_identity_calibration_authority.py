from __future__ import annotations

import copy
import hashlib
import json

import pytest

from bodyrig.photoreal_identity_calibration import _canonical_calibration_digest
from bodyrig.photoreal_identity_calibration_authority import (
    PhotorealIdentityCalibrationAuthorityError,
    bind_negative_inventory_provenance,
    validate_identity_calibration_integrity,
    validate_negative_inventory_binding,
)
from bodyrig.photoreal_identity_negative_verify import canonical_identity_negative_inventory_sha256


def _inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-inventory",
        "version": 1,
        "target_performer_id": "42",
        "label_authority": "stash-single-performer-other-id-v1",
        "negative_performer_count": 2,
        "source_count": 2,
        "sources": [
            {
                "source_key": "scene:s7:E:/p7.mp4",
                "scene_id": "s7",
                "subject_performer_id": "7",
                "path": "E:/p7.mp4",
            },
            {
                "source_key": "image:i8:F:/p8.jpg",
                "image_id": "i8",
                "subject_performer_id": "8",
                "path": "F:/p8.jpg",
            },
        ],
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _bank() -> dict[str, object]:
    return {"performer_id": "42"}


def _plan(inventory: dict[str, object]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-calibration-plan",
        "version": 1,
        "target_performer_id": "42",
        "negative_inventory_sha256": canonical_identity_negative_inventory_sha256(inventory),
    }


def _calibration_core() -> dict[str, object]:
    calibration: dict[str, object] = {
        "format": "bodyrig-photoreal-identity-calibration",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": "b" * 64,
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
        "match_threshold": 0.625,
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
    calibration["identity_calibration_sha256"] = _canonical_calibration_digest(calibration)
    return calibration


def test_calibration_authority_accepts_exact_negative_inventory_digest() -> None:
    inventory = _inventory()
    expected = canonical_identity_negative_inventory_sha256(inventory)

    observed = validate_negative_inventory_binding(inventory, _plan(inventory), _bank())

    assert observed == expected


def test_calibration_authority_rejects_inventory_changed_after_plan() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    inventory["sources"][0]["path"] = "E:/substituted.mp4"

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="canonical digest mismatch"):
        validate_negative_inventory_binding(inventory, plan, _bank())


def test_calibration_authority_rejects_missing_plan_inventory_digest() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    plan.pop("negative_inventory_sha256")

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="plan negative inventory SHA-256"):
        validate_negative_inventory_binding(inventory, plan, _bank())


def test_calibration_authority_rejects_inventory_matching_authority_crossing() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["identity_matching_authorized"] = True
    plan = _plan(inventory)

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="crossed matching authority"):
        validate_negative_inventory_binding(inventory, plan, _bank())


def test_calibration_authority_rejects_wrong_target_even_with_resealed_digest() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["target_performer_id"] = "99"
    plan = _plan(inventory)
    plan["target_performer_id"] = "99"

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="inventory/bank performer mismatch"):
        validate_negative_inventory_binding(inventory, plan, _bank())


def test_canonical_inventory_digest_is_key_order_independent() -> None:
    inventory = _inventory()
    reordered = {key: inventory[key] for key in reversed(list(inventory.keys()))}

    assert canonical_identity_negative_inventory_sha256(reordered) == canonical_identity_negative_inventory_sha256(inventory)


def test_calibration_integrity_accepts_unbound_canonical_core() -> None:
    calibration = _calibration_core()

    observed = validate_identity_calibration_integrity(calibration)

    assert observed == calibration["identity_calibration_sha256"]


def test_calibration_provenance_seal_binds_core_and_negative_inventory() -> None:
    calibration = _calibration_core()
    core_sha256 = calibration["identity_calibration_sha256"]
    inventory_sha256 = "e" * 64

    sealed = bind_negative_inventory_provenance(calibration, inventory_sha256)

    binding = {
        "identity_calibration_core_sha256": core_sha256,
        "negative_inventory_sha256": inventory_sha256,
    }
    expected = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert sealed["identity_calibration_core_sha256"] == core_sha256
    assert sealed["negative_inventory_sha256"] == inventory_sha256
    assert sealed["identity_calibration_sha256"] == expected
    assert validate_identity_calibration_integrity(sealed) == expected
    assert "identity_calibration_core_sha256" not in calibration
    assert "negative_inventory_sha256" not in calibration
    assert calibration["identity_calibration_sha256"] == core_sha256


def test_calibration_provenance_seal_changes_with_negative_inventory() -> None:
    calibration = _calibration_core()

    first = bind_negative_inventory_provenance(calibration, "e" * 64)
    second = bind_negative_inventory_provenance(calibration, "f" * 64)

    assert first["identity_calibration_core_sha256"] == second["identity_calibration_core_sha256"]
    assert first["identity_calibration_sha256"] != second["identity_calibration_sha256"]


def test_calibration_provenance_seal_rejects_invalid_inventory_digest() -> None:
    calibration = _calibration_core()

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="negative inventory SHA-256"):
        bind_negative_inventory_provenance(calibration, "not-a-sha")


def test_calibration_provenance_seal_rejects_tampered_core_before_binding() -> None:
    calibration = _calibration_core()
    calibration["match_threshold"] = 0.7

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="canonical digest mismatch"):
        bind_negative_inventory_provenance(calibration, "e" * 64)


def test_calibration_integrity_rejects_tampered_bound_semantics() -> None:
    sealed = bind_negative_inventory_provenance(_calibration_core(), "e" * 64)
    sealed["match_threshold"] = 0.7

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="core canonical digest mismatch"):
        validate_identity_calibration_integrity(sealed)


def test_calibration_integrity_rejects_tampered_bound_inventory_digest() -> None:
    sealed = bind_negative_inventory_provenance(_calibration_core(), "e" * 64)
    sealed["negative_inventory_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="provenance digest mismatch"):
        validate_identity_calibration_integrity(sealed)


def test_calibration_integrity_rejects_tampered_outer_digest() -> None:
    sealed = bind_negative_inventory_provenance(_calibration_core(), "e" * 64)
    sealed["identity_calibration_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="provenance digest mismatch"):
        validate_identity_calibration_integrity(sealed)


def test_calibration_integrity_rejects_tampered_declared_core_digest() -> None:
    sealed = bind_negative_inventory_provenance(_calibration_core(), "e" * 64)
    sealed["identity_calibration_core_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="core canonical digest mismatch"):
        validate_identity_calibration_integrity(sealed)


def test_calibration_integrity_rejects_half_bound_provenance() -> None:
    calibration = _calibration_core()
    calibration["negative_inventory_sha256"] = "e" * 64

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="binding is incomplete"):
        validate_identity_calibration_integrity(calibration)


def test_calibration_provenance_seal_rejects_rebinding() -> None:
    sealed = bind_negative_inventory_provenance(_calibration_core(), "e" * 64)

    with pytest.raises(PhotorealIdentityCalibrationAuthorityError, match="already provenance-bound"):
        bind_negative_inventory_provenance(sealed, "f" * 64)
