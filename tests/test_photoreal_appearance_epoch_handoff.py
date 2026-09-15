from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_appearance_epoch_handoff import (
    PhotorealAppearanceEpochHandoffError,
    build_appearance_epoch_review_handoff,
    build_appearance_epoch_review_handoff_files,
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


def test_handoff_preserves_all_candidates_without_selecting_or_approving() -> None:
    handoff, review = build_appearance_epoch_review_handoff(_plan())

    assert handoff["source_group_count"] == 3
    assert handoff["train_source_group_count"] == 2
    assert handoff["evaluation_source_group_count"] == 1
    assert {item["group_id"] for item in handoff["candidate_source_groups"]} == {
        "scene:train-a",
        "scene:train-b",
        "scene:eval-a",
    }
    assert handoff["human_review_complete"] is False
    assert handoff["human_approved"] is False
    assert handoff["teacher_input_authorized"] is False
    assert handoff["teacher_training_authorized"] is False
    assert handoff["photoreal_acceptance_authority"] is False
    assert handoff["production_activation"] is False

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
    assert review["selected_epoch_id"] is None
    assert review["selected_source_group_ids"] == []
    assert review["human_review_complete"] is False
    assert review["human_approved"] is False
    assert review["reviewed_by"] == ""
    assert review["production_activation"] is False


def test_handoff_rejects_resealed_authority_crossing() -> None:
    plan = copy.deepcopy(_plan())
    plan["teacher_training_authorized"] = True
    plan.pop("appearance_epoch_plan_sha256")
    plan["appearance_epoch_plan_sha256"] = _digest(plan)

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="crossed teacher authority"):
        build_appearance_epoch_review_handoff(plan)


def test_handoff_rejects_tampered_plan_digest() -> None:
    plan = copy.deepcopy(_plan())
    plan["eligible_observation_count"] = 6

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="plan digest mismatch"):
        build_appearance_epoch_review_handoff(plan)


def test_handoff_rejects_boolean_version_even_if_resealed() -> None:
    plan = copy.deepcopy(_plan())
    plan["version"] = True
    plan.pop("appearance_epoch_plan_sha256")
    plan["appearance_epoch_plan_sha256"] = _digest(plan)

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="format/version mismatch"):
        build_appearance_epoch_review_handoff(plan)


def test_handoff_requires_train_and_evaluation_candidate_groups() -> None:
    plan = copy.deepcopy(_plan())
    plan["eligible_source_groups"] = [
        item for item in plan["eligible_source_groups"] if item["split"] == "train"
    ]
    plan["source_group_count"] = 2
    plan["eligible_observation_count"] = 3
    plan["eligible_evaluation_observation_count"] = 1
    plan.pop("appearance_epoch_plan_sha256")
    plan["appearance_epoch_plan_sha256"] = _digest(plan)

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="both train and held-out evaluation"):
        build_appearance_epoch_review_handoff(plan)


def test_handoff_files_are_create_only_and_do_not_partially_write(tmp_path: Path) -> None:
    plan_path = tmp_path / "appearance-epoch-plan.json"
    handoff_path = tmp_path / "review-handoff.json"
    review_path = tmp_path / "human-review.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    review_path.write_text("already-owned\n", encoding="utf-8")

    with pytest.raises(PhotorealAppearanceEpochHandoffError, match="review template already exists"):
        build_appearance_epoch_review_handoff_files(plan_path, handoff_path, review_path)

    assert handoff_path.exists() is False
    assert review_path.read_text(encoding="utf-8") == "already-owned\n"


def test_handoff_file_round_trip_binds_initial_review_template(tmp_path: Path) -> None:
    plan_path = tmp_path / "appearance-epoch-plan.json"
    handoff_path = tmp_path / "review-handoff.json"
    review_path = tmp_path / "human-review.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")

    handoff, review = build_appearance_epoch_review_handoff_files(plan_path, handoff_path, review_path)
    persisted_handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    persisted_review = json.loads(review_path.read_text(encoding="utf-8"))

    assert persisted_handoff == handoff
    assert persisted_review == review
    assert persisted_handoff["initial_review_template_sha256"] == _digest(persisted_review)
