from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_motion_evidence as evidence
import bodyrig.photoreal_p2_motion_input_plan as input_plan
from bodyrig.photoreal_p2_motion_input_plan import (
    PhotorealP2MotionInputPlanError,
    build_motion_input_plan,
    build_motion_input_plan_files,
    validate_motion_input_plan,
)
from bodyrig.photoreal_p2_motion_selection import build_motion_source_selection


def _candidate(
    *,
    ref: str,
    group: str,
    split: str,
    sha: str,
    preparation_mode: str = "direct-exavatar-video",
) -> dict[str, object]:
    projection = "flat" if preparation_mode == "direct-exavatar-video" else "vr180"
    stereo = "mono" if preparation_mode == "direct-exavatar-video" else "side-by-side"
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
        "projection": projection,
        "stereo_layout": stereo,
        "preparation_mode": preparation_mode,
        "authorized_observation_count": 2,
        "timestamped_observation_count": 2,
        "view_bins": ["front", "profile"],
        "coverage": ["face-front", "full-body-front"],
    }


def _artifacts(*, spatial_driver: bool = False) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    driver_mode = (
        "exact-authorized-deprojection-required"
        if spatial_driver
        else "direct-exavatar-video"
    )
    private: dict[str, object] = {
        "format": evidence.PRIVATE_INDEX_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
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
            {
                "source_ref": "src-unselected",
                "group_ref": "grp-extra",
                "split": "train",
                "source_key": "scene:extra:E:/extra.mp4",
                "group_id": "scene:extra",
                "resolved_path": r"\\stash\extra.mp4",
                "source_sha256": "e" * 64,
                "size_bytes": 123456,
            },
        ],
        "entry_count": 3,
        "build_private": True,
        "source_media_rehash_performed": False,
        "production_activation": False,
    }
    private["p2_motion_private_index_sha256"] = evidence._digest(
        private,
        omit="p2_motion_private_index_sha256",
    )

    handoff: dict[str, object] = {
        "format": evidence.HANDOFF_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "p2_animation_plan_sha256": "b" * 64,
        "p2_motion_private_index_sha256": private[
            "p2_motion_private_index_sha256"
        ],
        "motion_driver_candidates": [
            _candidate(
                ref="src-driver",
                group="grp-train",
                split="train",
                sha="c",
                preparation_mode=driver_mode,
            ),
            _candidate(
                ref="src-unselected",
                group="grp-extra",
                split="train",
                sha="e",
            ),
        ],
        "held_out_motion_validation_candidates": [
            _candidate(
                ref="src-heldout",
                group="grp-eval",
                split="evaluation",
                sha="d",
            ),
        ],
        "motion_driver_candidate_count": 2,
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

    selection = build_motion_source_selection(
        handoff,
        private,
        motion_driver_source_refs=["src-driver"],
        held_out_validation_source_refs=["src-heldout"],
        reviewed_by="operator",
        review_notes="Selected exact train and held-out motion sources.",
        approve_human_selection=True,
    )
    return handoff, private, selection


def test_motion_input_plan_contains_only_selected_private_sources() -> None:
    handoff, private, selection = _artifacts()

    plan = build_motion_input_plan(handoff, private, selection)

    assert plan["motion_driver_task_count"] == 1
    assert plan["held_out_motion_validation_task_count"] == 1
    assert plan["direct_flat_mono_task_count"] == 2
    assert plan["exact_deprojection_task_count"] == 0
    assert plan["motion_fitting_backend"] == "pinned-exavatar-fitting-v1"
    assert plan["motion_fitting_camera_mode"] == "virtual"
    assert plan["motion_input_plan_ready"] is True
    assert plan["p2_motion_input_authorized"] is True
    assert plan["motion_input_preparation_execution_authorized"] is False
    assert plan["p2_animation_execution_authorized"] is False
    assert plan["production_activation"] is False

    assert plan["motion_driver_tasks"][0]["resolved_path"] == r"\\stash\train.mp4"
    assert (
        plan["held_out_motion_validation_tasks"][0]["resolved_path"]
        == r"\\stash\eval.mp4"
    )
    serialized = json.dumps(plan, sort_keys=True)
    assert "extra.mp4" not in serialized
    assert "scene:extra:E:/extra.mp4" not in serialized


def test_motion_input_plan_routes_spatial_source_to_exact_deprojection() -> None:
    handoff, private, selection = _artifacts(spatial_driver=True)

    plan = build_motion_input_plan(handoff, private, selection)

    driver = plan["motion_driver_tasks"][0]
    assert driver["preparation_mode"] == "exact-authorized-deprojection-required"
    assert driver["normalization_action"] == "exact-authorized-deprojection"
    assert plan["exact_deprojection_task_count"] == 1
    assert plan["direct_flat_mono_task_count"] == 1


def test_motion_input_plan_rejects_resealed_private_path_substitution() -> None:
    handoff, private, selection = _artifacts()
    private["entries"][0]["resolved_path"] = r"\\stash\substituted.mp4"
    private["p2_motion_private_index_sha256"] = evidence._digest(
        private,
        omit="p2_motion_private_index_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionInputPlanError,
        match="authority readback failed",
    ):
        build_motion_input_plan(handoff, private, selection)


def test_motion_input_plan_validator_rejects_resealed_execution_authority() -> None:
    handoff, private, selection = _artifacts()
    plan = build_motion_input_plan(handoff, private, selection)
    plan["p2_animation_execution_authorized"] = True
    plan["p2_motion_input_plan_sha256"] = input_plan._digest(
        plan,
        omit="p2_motion_input_plan_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionInputPlanError,
        match="authority mismatch: p2_animation_execution_authorized",
    ):
        validate_motion_input_plan(
            plan,
            handoff=handoff,
            private_index=private,
            selection=selection,
        )


def test_motion_input_plan_validator_rejects_boolean_version() -> None:
    handoff, private, selection = _artifacts()
    plan = build_motion_input_plan(handoff, private, selection)
    plan["version"] = True
    plan["p2_motion_input_plan_sha256"] = input_plan._digest(
        plan,
        omit="p2_motion_input_plan_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionInputPlanError,
        match="format/version mismatch",
    ):
        validate_motion_input_plan(
            plan,
            handoff=handoff,
            private_index=private,
            selection=selection,
        )


def test_motion_input_plan_file_reuse_is_exact(tmp_path: Path) -> None:
    handoff, private, selection = _artifacts()
    handoff_path = tmp_path / "handoff.json"
    private_path = tmp_path / "private.json"
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "plan.json"
    handoff_path.write_text(json.dumps(handoff) + "\n", encoding="utf-8")
    private_path.write_text(json.dumps(private) + "\n", encoding="utf-8")
    selection_path.write_text(json.dumps(selection) + "\n", encoding="utf-8")

    first = build_motion_input_plan_files(
        handoff_path,
        private_path,
        selection_path,
        output_path,
    )
    second = build_motion_input_plan_files(
        handoff_path,
        private_path,
        selection_path,
        output_path,
        reuse_existing=True,
    )
    assert first == second

    tampered = copy.deepcopy(first)
    tampered["motion_input_preparation_execution_authorized"] = True
    output_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2MotionInputPlanError,
        match="differs from canonical current state",
    ):
        build_motion_input_plan_files(
            handoff_path,
            private_path,
            selection_path,
            output_path,
            reuse_existing=True,
        )
