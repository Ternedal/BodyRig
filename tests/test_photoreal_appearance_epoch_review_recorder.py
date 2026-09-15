from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_appearance_epoch_handoff import build_appearance_epoch_review_handoff
from bodyrig.photoreal_appearance_epoch_review import apply_appearance_epoch_review
from bodyrig.photoreal_appearance_epoch_review_recorder import (
    PhotorealAppearanceEpochReviewRecorderError,
    build_human_review_record,
    build_human_review_record_file,
)


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan() -> dict[str, object]:
    plan: dict[str, object] = {
        "format": "bodyrig-photoreal-appearance-epoch-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "strategy": "human-review-required-v1",
        "source_frame_index_model_set_sha256": "1" * 64,
        "identity_bank_sha256": "2" * 64,
        "identity_calibration_sha256": "3" * 64,
        "eligible_observation_count": 5,
        "eligible_train_observation_count": 3,
        "eligible_evaluation_observation_count": 2,
        "source_group_count": 3,
        "eligible_source_groups": [
            {
                "group_id": "scene:train-a",
                "split": "train",
                "source_keys": ["source:train-a"],
                "frame_sha256s": ["a" * 64, "b" * 64],
                "view_bins": ["front", "left-profile"],
                "eligible_observation_count": 2,
            },
            {
                "group_id": "scene:eval-a",
                "split": "evaluation",
                "source_keys": ["source:eval-a"],
                "frame_sha256s": ["c" * 64, "d" * 64],
                "view_bins": ["front", "right-profile"],
                "eligible_observation_count": 2,
            },
            {
                "group_id": "scene:train-b",
                "split": "train",
                "source_keys": ["source:train-b"],
                "frame_sha256s": ["e" * 64],
                "view_bins": ["rear"],
                "eligible_observation_count": 1,
            },
        ],
        "evidence_sha256": "4" * 64,
        "candidate_epochs": [],
        "selected_epoch_id": None,
        "human_epoch_review_required": True,
        "human_epoch_review_complete": False,
        "teacher_input_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    plan["appearance_epoch_plan_sha256"] = _digest(plan)
    return plan


def _handoff(plan: dict[str, object] | None = None) -> dict[str, object]:
    handoff, _ = build_appearance_epoch_review_handoff(plan or _plan())
    return handoff


def _record(plan: dict[str, object] | None = None, handoff: dict[str, object] | None = None) -> dict[str, object]:
    actual_plan = plan or _plan()
    actual_handoff = handoff or _handoff(actual_plan)
    return build_human_review_record(
        actual_plan,
        actual_handoff,
        selected_epoch_id="epoch-2026-09-a",
        selected_source_group_ids=["scene:train-a", "scene:eval-a"],
        reviewed_by="operator",
        review_notes="Human reviewed a coherent appearance state across train and held-out evidence.",
        approve_human_review=True,
    )


def test_recorder_writes_exact_existing_review_shape_and_gate_accepts_it() -> None:
    plan = _plan()
    review = _record(plan)

    assert set(review) == {
        "format",
        "version",
        "performer_id",
        "appearance_epoch_plan_sha256",
        "selected_epoch_id",
        "selected_source_group_ids",
        "human_review_complete",
        "human_approved",
        "reviewed_by",
        "review_notes",
        "production_activation",
    }
    assert review["selected_source_group_ids"] == ["scene:eval-a", "scene:train-a"]
    assert review["human_review_complete"] is True
    assert review["human_approved"] is True
    assert review["production_activation"] is False

    selection = apply_appearance_epoch_review(plan, review)
    assert selection["teacher_input_authorized"] is True
    assert selection["teacher_training_authorized"] is True
    assert selection["photoreal_acceptance_authority"] is False
    assert selection["production_activation"] is False


def test_recorder_requires_explicit_approval_flag() -> None:
    plan = _plan()
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="approve-human-review"):
        build_human_review_record(
            plan,
            _handoff(plan),
            selected_epoch_id="epoch-2026-09-a",
            selected_source_group_ids=["scene:train-a", "scene:eval-a"],
            reviewed_by="operator",
            review_notes="Reviewed.",
            approve_human_review=False,
        )


def test_recorder_rejects_unknown_handoff_group() -> None:
    plan = _plan()
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="not present in the handoff"):
        build_human_review_record(
            plan,
            _handoff(plan),
            selected_epoch_id="epoch-2026-09-a",
            selected_source_group_ids=["scene:train-a", "scene:unknown"],
            reviewed_by="operator",
            review_notes="Reviewed.",
            approve_human_review=True,
        )


def test_recorder_requires_train_and_held_out_evaluation_selection() -> None:
    plan = _plan()
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="train and one held-out evaluation"):
        build_human_review_record(
            plan,
            _handoff(plan),
            selected_epoch_id="epoch-2026-09-a",
            selected_source_group_ids=["scene:train-a", "scene:train-b"],
            reviewed_by="operator",
            review_notes="Reviewed.",
            approve_human_review=True,
        )


def test_recorder_rejects_tampered_handoff_digest() -> None:
    plan = _plan()
    handoff = copy.deepcopy(_handoff(plan))
    handoff["performer_name"] = "tampered"

    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="handoff digest mismatch"):
        _record(plan, handoff)


def test_recorder_rejects_resealed_handoff_that_crosses_authority() -> None:
    plan = _plan()
    handoff = copy.deepcopy(_handoff(plan))
    handoff["teacher_training_authorized"] = True
    handoff.pop("appearance_epoch_review_handoff_sha256")
    handoff["appearance_epoch_review_handoff_sha256"] = _digest(handoff)

    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="crossed teacher authority"):
        _record(plan, handoff)


def test_recorder_rejects_handoff_from_different_plan() -> None:
    plan = _plan()
    other_plan = copy.deepcopy(plan)
    other_plan["performer_name"] = "Different evidence package"
    other_plan.pop("appearance_epoch_plan_sha256")
    other_plan["appearance_epoch_plan_sha256"] = _digest(other_plan)
    handoff = _handoff(other_plan)

    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="different plan"):
        _record(plan, handoff)


def test_recorder_requires_nonempty_review_notes() -> None:
    plan = _plan()
    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="review notes must be non-empty"):
        build_human_review_record(
            plan,
            _handoff(plan),
            selected_epoch_id="epoch-2026-09-a",
            selected_source_group_ids=["scene:train-a", "scene:eval-a"],
            reviewed_by="operator",
            review_notes="   ",
            approve_human_review=True,
        )


def test_record_file_is_create_only(tmp_path: Path) -> None:
    plan = _plan()
    handoff = _handoff(plan)
    plan_path = tmp_path / "plan.json"
    handoff_path = tmp_path / "handoff.json"
    output_path = tmp_path / "human-review.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    output_path.write_text("already-owned\n", encoding="utf-8")

    with pytest.raises(PhotorealAppearanceEpochReviewRecorderError, match="already exists"):
        build_human_review_record_file(
            plan_path,
            handoff_path,
            output_path,
            selected_epoch_id="epoch-2026-09-a",
            selected_source_group_ids=["scene:train-a", "scene:eval-a"],
            reviewed_by="operator",
            review_notes="Reviewed.",
            approve_human_review=True,
        )

    assert output_path.read_text(encoding="utf-8") == "already-owned\n"
