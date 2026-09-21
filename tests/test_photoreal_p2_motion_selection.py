from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_motion_evidence as evidence
import bodyrig.photoreal_p2_motion_selection as selection
from bodyrig.photoreal_p2_motion_selection import (
    PhotorealP2MotionSelectionError,
    build_motion_source_selection,
    record_motion_source_selection_files,
    validate_motion_source_selection,
)


def _candidate(*, ref: str, group: str, split: str, sha: str) -> dict[str, object]:
    return {
        "source_ref": ref,
        "group_ref": group,
        "split": split,
        "kind": "video",
        "source_sha256": sha * 64,
        "size_bytes": 123456,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "flat",
        "stereo_layout": "mono",
        "preparation_mode": "direct-exavatar-video",
        "authorized_observation_count": 2,
        "timestamped_observation_count": 2,
        "view_bins": ["front", "profile"],
        "coverage": ["face-front", "full-body-front"],
    }


def _artifacts() -> tuple[dict[str, object], dict[str, object]]:
    handoff: dict[str, object] = {
        "format": evidence.HANDOFF_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
        "motion_driver_candidates": [
            _candidate(ref="src-driver", group="grp-train", split="train", sha="c"),
        ],
        "held_out_motion_validation_candidates": [
            _candidate(ref="src-heldout", group="grp-eval", split="evaluation", sha="d"),
        ],
        "motion_driver_candidate_count": 1,
        "held_out_motion_validation_candidate_count": 1,
        "operator_requirements": {
            "select_at_least_one_training_split_motion_driver": True,
            "select_at_least_one_evaluation_split_validation_source": True,
            "preserve_train_evaluation_group_disjointness": True,
            "never_use_evaluation_bytes_for_appearance_training": True,
            "require_exact_deprojection_before_fit_when_flagged": True,
            "record_human_selection": True,
        },
        "source_media_rehash_performed": False,
        "human_motion_source_selection_required": True,
        "human_motion_source_selection_complete": False,
        "p2_motion_input_authorized": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    handoff["p2_motion_evidence_handoff_sha256"] = evidence._digest(
        handoff,
        omit="p2_motion_evidence_handoff_sha256",
    )
    private: dict[str, object] = {
        "format": evidence.PRIVATE_INDEX_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
        "p2_motion_evidence_handoff_sha256": handoff[
            "p2_motion_evidence_handoff_sha256"
        ],
        "entries": [
            {
                "source_ref": "src-driver",
                "group_ref": "grp-train",
                "split": "train",
                "source_key": "scene:train:E:/train.mp4",
                "group_id": "scene:train",
                "resolved_path": r"\\stash\train.mp4",
                "source_sha256": "c" * 64,
                "size_bytes": 123456,
            },
            {
                "source_ref": "src-heldout",
                "group_ref": "grp-eval",
                "split": "evaluation",
                "source_key": "scene:eval:E:/eval.mp4",
                "group_id": "scene:eval",
                "resolved_path": r"\\stash\eval.mp4",
                "source_sha256": "d" * 64,
                "size_bytes": 123456,
            },
        ],
        "entry_count": 2,
        "build_private": True,
        "source_media_rehash_performed": False,
        "production_activation": False,
    }
    private["p2_motion_private_index_sha256"] = evidence._digest(
        private,
        omit="p2_motion_private_index_sha256",
    )
    evidence.validate_motion_evidence_handoff(handoff)
    evidence.validate_private_motion_index(private, handoff=handoff)
    return handoff, private


def test_motion_selection_requires_explicit_human_approval() -> None:
    handoff, private = _artifacts()

    with pytest.raises(
        PhotorealP2MotionSelectionError,
        match="requires explicit human approval",
    ):
        build_motion_source_selection(
            handoff,
            private,
            motion_driver_source_refs=["src-driver"],
            held_out_validation_source_refs=["src-heldout"],
            reviewed_by="operator",
            review_notes="Reviewed both source roles.",
            approve_human_selection=False,
        )


def test_motion_selection_authorizes_input_preparation_only_and_hides_paths() -> None:
    handoff, private = _artifacts()

    receipt = build_motion_source_selection(
        handoff,
        private,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Selected one TRAIN driver and one HELD-OUT EVALUATION source.",
        approve_human_selection=True,
    )

    assert receipt["motion_source_selection_authority"] is True
    assert receipt["p2_motion_input_authorized"] is True
    assert receipt["p2_animation_execution_authorized"] is False
    assert receipt["p2_animated_teacher_acceptance_authority"] is False
    assert receipt["quest_distillation_authorized"] is False
    assert receipt["production_activation"] is False
    assert receipt["source_media_rehash_required"] is False
    assert receipt["source_media_rehash_performed"] is False
    serialized = json.dumps(receipt, sort_keys=True)
    assert "E:/train.mp4" not in serialized
    assert "E:/eval.mp4" not in serialized
    assert "\\\\stash" not in serialized
    assert "resolved_path" not in serialized
    assert "source_key" not in serialized


def test_motion_selection_rejects_cross_split_source_refs() -> None:
    handoff, private = _artifacts()

    with pytest.raises(
        PhotorealP2MotionSelectionError,
        match="outside TRAIN candidates",
    ):
        build_motion_source_selection(
            handoff,
            private,
            motion_driver_source_refs=["src-heldout"],
            held_out_validation_source_refs=["src-heldout"],
            reviewed_by="operator",
            review_notes="Invalid cross-split selection.",
            approve_human_selection=True,
        )


def test_motion_selection_rejects_resealed_private_index_drift() -> None:
    handoff, private = _artifacts()
    private["entries"][0]["resolved_path"] = r"\\stash\substituted.mp4"
    private["p2_motion_private_index_sha256"] = evidence._digest(
        private,
        omit="p2_motion_private_index_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionSelectionError,
        match="private/public P2 motion binding mismatch|strict readback failed",
    ):
        build_motion_source_selection(
            handoff,
            private,
            motion_driver_source_refs=["src-driver"],
            held_out_validation_source_refs=["src-heldout"],
            reviewed_by="operator",
            review_notes="Should not accept private map drift.",
            approve_human_selection=True,
        )


def test_motion_selection_validator_rejects_resealed_authority_escalation() -> None:
    handoff, private = _artifacts()
    receipt = build_motion_source_selection(
        handoff,
        private,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Valid receipt before tamper.",
        approve_human_selection=True,
    )
    receipt["p2_animation_execution_authorized"] = True
    receipt["p2_motion_source_selection_sha256"] = selection._digest(
        receipt,
        omit="p2_motion_source_selection_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionSelectionError,
        match="authority mismatch: p2_animation_execution_authorized",
    ):
        validate_motion_source_selection(
            receipt,
            handoff=handoff,
            private_index=private,
        )


def test_motion_selection_file_reuse_is_exact(tmp_path: Path) -> None:
    handoff, private = _artifacts()
    handoff_path = tmp_path / "handoff.json"
    private_path = tmp_path / "private.json"
    output = tmp_path / "selection.json"
    handoff_path.write_text(json.dumps(handoff, sort_keys=True) + "\n", encoding="utf-8")
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")

    first = record_motion_source_selection_files(
        handoff_path,
        private_path,
        output,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Reviewed source selection.",
        approve_human_selection=True,
    )
    second = record_motion_source_selection_files(
        handoff_path,
        private_path,
        output,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Reviewed source selection.",
        approve_human_selection=True,
        reuse_existing=True,
    )
    assert first == second

    tampered = copy.deepcopy(first)
    tampered["review_notes"] = "tampered"
    output.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2MotionSelectionError,
        match="differs from canonical current state",
    ):
        record_motion_source_selection_files(
            handoff_path,
            private_path,
            output,
            motion_driver_source_refs=["src-driver"],
            held_out_validation_source_refs=["src-heldout"],
            reviewed_by="operator",
            review_notes="Reviewed source selection.",
            approve_human_selection=True,
            reuse_existing=True,
        )
