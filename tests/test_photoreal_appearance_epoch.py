from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_appearance_epoch import (
    PhotorealAppearanceEpochError,
    build_appearance_epoch_plan,
)


def _observation(*, split: str, source: str, group: str, frame: str) -> dict[str, object]:
    return {
        "source_key": source,
        "source_sha256": "a" * 64,
        "split": split,
        "group_id": group,
        "kind": "video",
        "timestamp_seconds": 1.0,
        "eye": "mono",
        "projection": "flat",
        "frame_sha256": frame * 64,
        "perceptual_hash": "0123456789abcdef",
        "width": 3840,
        "height": 2160,
        "view_bin": "front",
        "face_visibility": 0.9,
        "full_body_visibility": 0.9,
        "person_fraction": 0.8,
        "sharpness": 0.9,
        "motion": 0.1,
        "occlusion": 0.05,
        "identity_measurement_status": "available",
        "identity_similarity": 0.95,
        "target_identity_verified": True,
        "identity_authority": "calibrated-identity-bank-v1",
        "eligible_for_teacher": True,
        "coverage": ["face-front", "full-body-front"],
    }


def _frame_index() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-index",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "analyzer_model_set_sha256": "c" * 64,
        "identity_bank_sha256": "d" * 64,
        "identity_calibration_sha256": "e" * 64,
        "observations": [
            _observation(split="train", source="scene:t:E:/train.mp4", group="scene:t", frame="1"),
            _observation(split="evaluation", source="scene:e:E:/eval.mp4", group="scene:e", frame="2"),
        ],
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_epoch_plan_never_auto_selects_or_authorizes_teacher_input() -> None:
    result = build_appearance_epoch_plan(_frame_index())

    assert result["performer_id"] == "42"
    assert result["eligible_observation_count"] == 2
    assert result["candidate_epochs"] == []
    assert result["selected_epoch_id"] is None
    assert result["human_epoch_review_required"] is True
    assert result["human_epoch_review_complete"] is False
    assert result["teacher_input_authorized"] is False
    assert result["teacher_training_authorized"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert len(result["appearance_epoch_plan_sha256"]) == 64


def test_epoch_plan_rejects_frame_index_without_training_authority() -> None:
    index = copy.deepcopy(_frame_index())
    index["teacher_training_authorized"] = False
    with pytest.raises(PhotorealAppearanceEpochError, match="teacher-training-authorized"):
        build_appearance_epoch_plan(index)


def test_epoch_plan_rejects_teacher_eligible_unverified_identity() -> None:
    index = copy.deepcopy(_frame_index())
    index["observations"][0]["target_identity_verified"] = False
    with pytest.raises(PhotorealAppearanceEpochError, match="lacks target identity authority"):
        build_appearance_epoch_plan(index)


def test_epoch_plan_requires_train_and_evaluation_evidence() -> None:
    index = copy.deepcopy(_frame_index())
    index["observations"][1]["eligible_for_teacher"] = False
    with pytest.raises(PhotorealAppearanceEpochError, match="eligible train and evaluation"):
        build_appearance_epoch_plan(index)
