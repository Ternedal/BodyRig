from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_teacher_input import PhotorealTeacherInputError, build_teacher_input


def _source(key: str, group: str, split: str) -> dict[str, object]:
    return {
        "kind": "video",
        "source_id": key,
        "group_id": group,
        "path": key.split(":", 2)[-1],
        "information_score": 100.0,
        "projection": "flat",
        "stereo_layout": "mono",
        "width": 3840,
        "height": 2160,
        "duration_seconds": 120.0,
        "frame_rate": 30.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }


def _plan() -> dict[str, object]:
    train = _source("scene:t:E:/train.mp4", "scene:t", "train")
    evaluation = _source("scene:e:E:/eval.mp4", "scene:e", "evaluation")
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [train],
        "evaluation": [evaluation],
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "sources": [
            {
                "kind": "video",
                "source_key": "scene:t:E:/train.mp4",
                "resolved_path": r"\\stash\VR_E\train.mp4",
                "size_bytes": 100,
                "sha256": "a" * 64,
            },
            {
                "kind": "video",
                "source_key": "scene:e:E:/eval.mp4",
                "resolved_path": r"\\stash\VR_E\eval.mp4",
                "size_bytes": 200,
                "sha256": "b" * 64,
            },
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observation(*, source: str, group: str, split: str, frame: str, view: str, coverage: list[str]) -> dict[str, object]:
    return {
        "source_key": source,
        "group_id": group,
        "split": split,
        "frame_sha256": frame * 64,
        "timestamp_seconds": 1.0,
        "eye": "mono",
        "view_bin": view,
        "coverage": coverage,
        "target_identity_verified": True,
        "eligible_for_teacher": True,
    }


def _frame_index() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-index",
        "version": 1,
        "performer_id": "42",
        "identity_bank_sha256": "c" * 64,
        "identity_calibration_sha256": "d" * 64,
        "analyzer_model_set_sha256": "e" * 64,
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "observations": [
            _observation(
                source="scene:t:E:/train.mp4",
                group="scene:t",
                split="train",
                frame="1",
                view="front",
                coverage=["face-front", "full-body-front"],
            ),
            _observation(
                source="scene:e:E:/eval.mp4",
                group="scene:e",
                split="evaluation",
                frame="2",
                view="front",
                coverage=["face-front", "full-body-front"],
            ),
        ],
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _selection() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-appearance-epoch-selection",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "selected_source_group_ids": ["scene:t", "scene:e"],
        "appearance_epoch_selection_sha256": "f" * 64,
        "human_epoch_review_complete": True,
        "human_approved": True,
        "teacher_input_authorized": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_teacher_input_keeps_training_and_eval_sources_separate() -> None:
    result = build_teacher_input(_plan(), _receipt(), _frame_index(), _selection())

    assert [item["source_key"] for item in result["training_sources"]] == ["scene:t:E:/train.mp4"]
    assert [item["source_key"] for item in result["held_out_evaluation_sources"]] == ["scene:e:E:/eval.mp4"]
    assert result["evaluation_bytes_excluded_from_teacher_request"] is True
    assert result["held_out_view_coverage_missing"] == []
    assert result["teacher_training_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["human_visual_acceptance_required"] is True
    assert result["production_activation"] is False


def test_teacher_input_requires_explicit_human_epoch_approval() -> None:
    selection = copy.deepcopy(_selection())
    selection["human_approved"] = False
    with pytest.raises(PhotorealTeacherInputError, match="explicit human approval"):
        build_teacher_input(_plan(), _receipt(), _frame_index(), selection)


def test_teacher_input_rejects_epoch_that_loses_held_out_coverage() -> None:
    index = copy.deepcopy(_frame_index())
    index["observations"][1]["coverage"] = ["face-front"]
    with pytest.raises(PhotorealTeacherInputError, match="loses required held-out evaluation coverage"):
        build_teacher_input(_plan(), _receipt(), index, _selection())


def test_teacher_input_rejects_plan_receipt_universe_mismatch() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"].pop()
    with pytest.raises(PhotorealTeacherInputError, match="source universe mismatch"):
        build_teacher_input(_plan(), receipt, _frame_index(), _selection())


def test_teacher_input_rejects_selected_group_without_eligible_observation() -> None:
    selection = copy.deepcopy(_selection())
    selection["selected_source_group_ids"].append("scene:ghost")
    with pytest.raises(PhotorealTeacherInputError, match="selected groups without eligible observations"):
        build_teacher_input(_plan(), _receipt(), _frame_index(), selection)
