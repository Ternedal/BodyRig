from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_animation_execution_receipt import (
    PhotorealAnimationExecutionReceiptError,
    build_animation_execution_receipt,
    validate_animation_execution_receipt,
)
from bodyrig.photoreal_animation_plan import ANIMATION_REQUIREMENTS


def _validated_result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-animation-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "adapter": "animation-adapter",
        "adapter_revision": "revision-a",
        "representation": "animated-teacher",
        "animation_complete": True,
        "consumed_teacher_artifacts": [
            {"relative_path": "checkpoint/teacher.bin", "sha256": "e" * 64}
        ],
        "implemented_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "animation_artifacts": [
            {
                "kind": "animated-teacher",
                "relative_path": "animation/clip.bin",
                "size_bytes": 123,
                "sha256": "f" * 64,
            }
        ],
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }


def test_execution_receipt_is_digest_bound_and_non_accepting() -> None:
    receipt = build_animation_execution_receipt(_validated_result())
    validated = validate_animation_execution_receipt(receipt)
    assert validated["animation_complete"] is True
    assert validated["artifact_bytes_verified_by_core"] is True
    assert validated["animated_teacher_acceptance_authority"] is False
    assert validated["human_animated_visual_acceptance_required"] is True
    assert validated["p3_device_distillation_authorized"] is False
    assert validated["production_activation"] is False
    assert len(validated["animation_execution_receipt_sha256"]) == 64


def test_execution_receipt_rejects_post_validation_tamper() -> None:
    receipt = build_animation_execution_receipt(_validated_result())
    receipt["representation"] = "silently-replaced"
    with pytest.raises(PhotorealAnimationExecutionReceiptError, match="does not match content"):
        validate_animation_execution_receipt(receipt)


def test_execution_receipt_rejects_boolean_v1_even_if_digest_field_exists() -> None:
    receipt = build_animation_execution_receipt(_validated_result())
    receipt["version"] = True
    with pytest.raises(PhotorealAnimationExecutionReceiptError, match="numeric v1"):
        validate_animation_execution_receipt(receipt)


def test_execution_receipt_builder_rejects_result_that_self_authorizes_p3() -> None:
    result = _validated_result()
    result["p3_device_distillation_authorized"] = True
    with pytest.raises(PhotorealAnimationExecutionReceiptError, match="prematurely authorized P3"):
        build_animation_execution_receipt(result)


def test_execution_receipt_builder_rejects_incomplete_motion_validation_universe() -> None:
    result = _validated_result()
    result["implemented_validation_dimensions"] = list(ANIMATION_REQUIREMENTS[:-1])
    with pytest.raises(PhotorealAnimationExecutionReceiptError, match="validation universe is incomplete"):
        build_animation_execution_receipt(result)


def test_execution_receipt_rejects_duplicate_animation_artifact_paths_when_resealed_shape_is_otherwise_valid() -> None:
    receipt = build_animation_execution_receipt(_validated_result())
    duplicate = copy.deepcopy(receipt["animation_artifacts"][0])
    receipt["animation_artifacts"].append(duplicate)
    with pytest.raises(PhotorealAnimationExecutionReceiptError, match="repeats animation artifact"):
        validate_animation_execution_receipt(receipt)
