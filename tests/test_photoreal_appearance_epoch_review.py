from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_appearance_epoch_review import (
    PhotorealAppearanceEpochReviewError,
    _digest,
    apply_appearance_epoch_review,
)


def _plan() -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-appearance-epoch-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "eligible_source_groups": [
            {"group_id": "scene:t", "split": "train"},
            {"group_id": "scene:e", "split": "evaluation"},
            {"group_id": "scene:t2", "split": "train"},
        ],
        "human_epoch_review_required": True,
        "human_epoch_review_complete": False,
        "teacher_input_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["appearance_epoch_plan_sha256"] = _digest(value)
    return value


def _reseal_plan(value: dict[str, object]) -> dict[str, object]:
    value = copy.deepcopy(value)
    value.pop("appearance_epoch_plan_sha256", None)
    value["appearance_epoch_plan_sha256"] = _digest(value)
    return value


def _review() -> dict[str, object]:
    plan = _plan()
    return {
        "format": "bodyrig-photoreal-appearance-epoch-review",
        "version": 1,
        "performer_id": "42",
        "appearance_epoch_plan_sha256": plan["appearance_epoch_plan_sha256"],
        "selected_epoch_id": "epoch-2026-a",
        "selected_source_group_ids": ["scene:t", "scene:e"],
        "human_review_complete": True,
        "human_approved": True,
        "reviewed_by": "operator",
        "review_notes": "Same coherent appearance state.",
        "production_activation": False,
    }


def test_explicit_human_review_can_authorize_epoch_teacher_input() -> None:
    result = apply_appearance_epoch_review(_plan(), _review())

    assert result["selected_epoch_id"] == "epoch-2026-a"
    assert result["selected_source_group_ids"] == ["scene:e", "scene:t"]
    assert result["selected_train_group_count"] == 1
    assert result["selected_evaluation_group_count"] == 1
    assert result["human_epoch_review_complete"] is True
    assert result["human_approved"] is True
    assert result["teacher_input_authorized"] is True
    assert result["teacher_training_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["human_visual_acceptance_required"] is True
    assert result["production_activation"] is False


def test_epoch_review_never_accepts_implicit_or_incomplete_human_approval() -> None:
    review = copy.deepcopy(_review())
    review["human_approved"] = False
    with pytest.raises(PhotorealAppearanceEpochReviewError, match="explicit completed human approval"):
        apply_appearance_epoch_review(_plan(), review)


def test_epoch_review_rejects_unknown_group() -> None:
    review = copy.deepcopy(_review())
    review["selected_source_group_ids"] = ["scene:t", "scene:unknown"]
    with pytest.raises(PhotorealAppearanceEpochReviewError, match="unknown source groups"):
        apply_appearance_epoch_review(_plan(), review)


def test_epoch_review_requires_both_train_and_eval_groups() -> None:
    review = copy.deepcopy(_review())
    review["selected_source_group_ids"] = ["scene:t", "scene:t2"]
    with pytest.raises(PhotorealAppearanceEpochReviewError, match="both train and held-out evaluation"):
        apply_appearance_epoch_review(_plan(), review)


def test_epoch_review_rejects_plan_digest_mismatch() -> None:
    review = copy.deepcopy(_review())
    review["appearance_epoch_plan_sha256"] = "f" * 64
    with pytest.raises(PhotorealAppearanceEpochReviewError, match="different plan"):
        apply_appearance_epoch_review(_plan(), review)


def test_epoch_review_rejects_extra_authority_fields() -> None:
    review = copy.deepcopy(_review())
    review["photoreal_acceptance"] = True
    with pytest.raises(PhotorealAppearanceEpochReviewError, match="fields must match v1 exactly"):
        apply_appearance_epoch_review(_plan(), review)


def test_epoch_review_rejects_boolean_plan_v1_before_authority_use() -> None:
    plan = _plan()
    plan["version"] = True
    with pytest.raises(
        PhotorealAppearanceEpochReviewError,
        match="plan format/version mismatch",
    ):
        apply_appearance_epoch_review(plan, _review())


def test_epoch_review_rejects_resealed_plan_content_drift() -> None:
    plan = _plan()
    plan["performer_id"] = "99"
    with pytest.raises(
        PhotorealAppearanceEpochReviewError,
        match="plan digest mismatch",
    ):
        apply_appearance_epoch_review(plan, _review())


def test_epoch_review_rejects_non_string_plan_sha() -> None:
    plan = _plan()
    plan["appearance_epoch_plan_sha256"] = True
    with pytest.raises(
        PhotorealAppearanceEpochReviewError,
        match="plan SHA-256 is invalid",
    ):
        apply_appearance_epoch_review(plan, _review())


def test_epoch_review_preserves_numeric_float_v1() -> None:
    plan = _plan()
    plan["version"] = 1.0
    plan = _reseal_plan(plan)
    review = _review()
    review["version"] = 1.0
    review["appearance_epoch_plan_sha256"] = plan[
        "appearance_epoch_plan_sha256"
    ]

    result = apply_appearance_epoch_review(plan, review)

    assert result["teacher_input_authorized"] is True
    assert result["production_activation"] is False
