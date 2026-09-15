from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_calibration_authority import (
    PhotorealIdentityCalibrationAuthorityError,
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
