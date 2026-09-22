from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoreal_v2_operator_status as status
import bodyrig.photoreal_v2_operator_status_cli as status_cli

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
PERFORMER = "42"


def _write_json(path: Path, value: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value or {"fixture": True}) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    p0 = tmp_path / "p0"
    repo = tmp_path / "repo"
    teacher = tmp_path / "p0-teacher"
    p0.mkdir()
    repo.mkdir()
    teacher.mkdir()
    for script in status._REQUIRED_SCRIPTS:
        (repo / script).write_text("# fixture\n", encoding="utf-8")
    return p0, repo, teacher


def _trust_p0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        status,
        "resolve_authorized_p0_root",
        lambda root: (
            {
                "performer_id": PERFORMER,
                "bodyrig_revision": REVISION,
                "status": "teacher-training-authorized",
                "teacher_training_authorized": True,
            },
            Path(root) / "p0-status.json",
            Path(root) / "dataset-plan.json",
            Path(root) / "source-receipt.json",
            Path(root) / "frame-index.json",
        ),
    )
    monkeypatch.setattr(
        status,
        "validate_downstream_readiness",
        lambda *args, **kwargs: {"fixture": "ready"},
    )
    monkeypatch.setattr(status, "_git_checkout_branch", lambda root: "main")


def _appearance(teacher: Path) -> Path:
    root = teacher / "appearance-epoch-visual-review-fixture"
    _write_json(root / "appearance-epoch-visual-review-manifest.json")
    return root


def _teacher_ready(teacher: Path) -> None:
    _write_json(teacher / "teacher-input.json")
    _write_json(teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json")


def _p1_pass(monkeypatch: pytest.MonkeyPatch, teacher: Path) -> None:
    _write_json(teacher / "p1-static-teacher-review" / "p1-likeness-review.json")
    _write_json(
        teacher
        / "p1-static-teacher-review"
        / "likeness-review"
        / "p1-likeness-review-manifest.json"
    )
    monkeypatch.setattr(
        status,
        "validate_likeness_review_pack",
        lambda output_root: {
            "p1_likeness_review_manifest_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        status,
        "validate_likeness_review_receipt",
        lambda receipt, review_manifest=None: {
            "performer_id": PERFORMER,
            "selected_epoch_id": "epoch-a",
            "teacher_input_sha256": "1" * 64,
            "p1_likeness_review_manifest_sha256": "a" * 64,
            "p1_likeness_review_sha256": "b" * 64,
            "p1_static_teacher_status": "pass",
            "p2_animation_authorized": True,
        },
    )


def _p2_lineage() -> dict[str, str]:
    return {
        "performer_id": PERFORMER,
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
    }


def _p2_plan_authority() -> dict[str, str]:
    return {
        **_p2_lineage(),
        "p1_likeness_review_manifest_sha256": "a" * 64,
        "p1_likeness_review_sha256": "b" * 64,
    }


def _trust_p2_materialized_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    lineage = _p2_lineage()
    handoff = {
        **lineage,
        "p2_motion_evidence_handoff_sha256": "d" * 64,
        "p2_motion_private_index_sha256": "e" * 64,
    }
    private_index = {
        **lineage,
        "p2_motion_private_index_sha256": "e" * 64,
    }
    selection = {
        **lineage,
        "p2_motion_evidence_handoff_sha256": "d" * 64,
        "p2_motion_private_index_sha256": "e" * 64,
        "p2_motion_source_selection_sha256": "f" * 64,
    }
    input_plan = {
        **lineage,
        "p2_motion_evidence_handoff_sha256": "d" * 64,
        "p2_motion_private_index_sha256": "e" * 64,
        "p2_motion_source_selection_sha256": "f" * 64,
        "p2_motion_input_plan_sha256": "0" * 64,
    }
    normalization = {
        "performer_id": PERFORMER,
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_motion_input_plan_sha256": "0" * 64,
        "p2_motion_normalization_selection_sha256": "b" * 64,
    }
    window = {
        "performer_id": PERFORMER,
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_motion_input_plan_sha256": "0" * 64,
        "p2_motion_normalization_selection_sha256": "b" * 64,
        "p2_motion_window_selection_sha256": "6" * 64,
    }
    motion = {
        **lineage,
        "p2_motion_evidence_handoff_sha256": "d" * 64,
        "p2_motion_private_index_sha256": "e" * 64,
        "p2_motion_source_selection_sha256": "f" * 64,
        "p2_motion_input_plan_sha256": "0" * 64,
        "p2_motion_normalization_selection_sha256": "b" * 64,
        "p2_motion_window_selection_sha256": "6" * 64,
        "p2_motion_preparation_receipt_sha256": "7" * 64,
    }
    identity = {
        **lineage,
        "p2_exavatar_animation_identity_sha256": "8" * 64,
    }
    execution = {
        **lineage,
        "p2_exavatar_animation_identity_sha256": identity[
            "p2_exavatar_animation_identity_sha256"
        ],
        "p2_motion_preparation_receipt_sha256": motion[
            "p2_motion_preparation_receipt_sha256"
        ],
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
    }
    animation = {
        **lineage,
        "p2_exavatar_animation_execution_input_sha256": execution[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_exavatar_animation_execution_receipt_sha256": "9" * 64,
    }
    heldout_input = {
        **lineage,
        "held_out_motion": {"source_ref": "src-heldout"},
        "p2_exavatar_animation_execution_input_sha256": execution[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "train_animation_execution_receipt_sha256": animation[
            "p2_exavatar_animation_execution_receipt_sha256"
        ],
        "p2_exavatar_heldout_evaluation_input_sha256": "a" * 64,
    }
    heldout_receipt = {
        **lineage,
        "p2_exavatar_animation_execution_input_sha256": execution[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "train_animation_execution_receipt_sha256": animation[
            "p2_exavatar_animation_execution_receipt_sha256"
        ],
        "p2_exavatar_heldout_evaluation_input_sha256": heldout_input[
            "p2_exavatar_heldout_evaluation_input_sha256"
        ],
        "held_out_source_ref": "src-heldout",
    }
    monkeypatch.setattr(
        status,
        "validate_motion_evidence_handoff",
        lambda value: dict(handoff),
    )
    monkeypatch.setattr(
        status,
        "validate_private_motion_index",
        lambda value, handoff=None: dict(private_index),
    )
    monkeypatch.setattr(
        status,
        "validate_motion_source_selection",
        lambda value, handoff=None, private_index=None: dict(selection),
    )
    monkeypatch.setattr(
        status,
        "validate_motion_input_plan",
        lambda value, handoff=None, private_index=None, selection=None: dict(input_plan),
    )
    monkeypatch.setattr(
        status,
        "validate_normalization_selection",
        lambda value, input_plan=None: dict(normalization),
    )
    monkeypatch.setattr(
        status,
        "validate_motion_window_selection",
        lambda value, input_plan=None, normalization_selection=None: dict(window),
    )
    monkeypatch.setattr(
        status,
        "validate_motion_preparation_receipt",
        lambda value: dict(motion),
    )
    monkeypatch.setattr(
        status,
        "validate_exavatar_animation_identity",
        lambda value, output_root=None: dict(identity),
    )
    monkeypatch.setattr(
        status,
        "validate_exavatar_animation_execution_input",
        lambda value: dict(execution),
    )
    monkeypatch.setattr(
        status,
        "validate_animation_execution_receipt",
        lambda value: dict(animation),
    )
    monkeypatch.setattr(
        status,
        "validate_heldout_evaluation_input",
        lambda value: dict(heldout_input),
    )
    monkeypatch.setattr(
        status,
        "validate_heldout_evaluation_receipt",
        lambda value: dict(heldout_receipt),
    )
    monkeypatch.setattr(
        status,
        "validate_animated_human_review_pack",
        lambda output_root, expected_review_plan=None: {
            "p2_heldout_animated_review_manifest_sha256": "5" * 64,
            "p2_heldout_animated_review_plan_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(
        status,
        "revalidate_heldout_animated_review_plan",
        lambda value, evaluation_workspaces=None: {
            "p2_heldout_animated_review_plan_sha256": "c" * 64
        },
    )

def _p2_pass_review() -> dict[str, object]:
    return {
        **_p2_lineage(),
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_heldout_animated_review_plan_sha256": "c" * 64,
        "p2_heldout_animated_human_review_sha256": "4" * 64,
        "human_animated_review_status": "pass",
        "p3_device_distillation_authorized": True,
    }


def _p2_intermediate_ready(
    monkeypatch: pytest.MonkeyPatch,
    teacher: Path,
) -> tuple[Path, str]:
    _trust_p2_materialized_chain(monkeypatch)
    p2 = teacher / "p2-animated-teacher"
    _write_json(p2 / "p2-animation-plan.json")
    monkeypatch.setattr(
        status,
        "validate_p2_animation_plan",
        lambda value: _p2_plan_authority(),
    )
    _write_json(p2 / "motion-evidence" / "p2-motion-evidence-handoff.json")
    _write_json(p2 / "motion-evidence" / "private-motion-source-index.json")
    _write_json(p2 / "p2-motion-source-selection.json")
    monkeypatch.setattr(
        status,
        "_selected_motion_refs",
        lambda *args, **kwargs: (["src-driver"], ["src-heldout"]),
    )
    _write_json(p2 / "motion-input" / "p2-motion-input-plan.json")
    _write_json(p2 / "motion-input" / "p2-motion-normalization-selection.json")
    _write_json(p2 / "motion-input" / "p2-motion-window-selection.json")
    _write_json(p2 / "motion-preparation" / "motion-preparation-receipt.json")
    _write_json(
        p2
        / "animation-input"
        / "exavatar-identity"
        / "p2-exavatar-animation-identity.json"
    )
    _write_json(
        p2
        / "animation-input"
        / "exavatar-execution"
        / "p2-exavatar-animation-execution-input.json"
    )
    _write_json(p2 / "animation-execution" / "animation-execution-receipt.json")
    _write_json(
        p2
        / "animation-evaluation"
        / "heldout-input"
        / "src-heldout"
        / "p2-exavatar-heldout-evaluation-input.json"
    )
    _write_json(
        p2
        / "animation-evaluation"
        / "heldout-execution"
        / "src-heldout"
        / "heldout-evaluation-execution-receipt.json"
    )
    _write_json(p2 / "animated-review" / "p2-heldout-animated-review-plan.json")
    _write_json(
        p2
        / "animated-review"
        / "human-review"
        / "p2-heldout-animated-human-review-manifest.json"
    )
    return p2, "src-heldout"


def _base_ready(
    monkeypatch: pytest.MonkeyPatch,
    p0: Path,
    teacher: Path,
) -> None:
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    _appearance(teacher)
    _teacher_ready(teacher)
    monkeypatch.setattr(
        status,
        "validate_teacher_input_document",
        lambda value: dict(value),
    )
    _p1_pass(monkeypatch, teacher)


def test_missing_readiness_points_to_checkout_bound_post_p0_operator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert result["read_only"] is True
    assert result["next_gate"] == "p0_downstream_readiness"
    assert "continue-photoreal-v2-teacher.ps1" in result["next_command"]
    assert str(p0.resolve()) in result["next_command"]
    assert result["production_activation"] is False


def test_checkout_mismatch_suppresses_executable_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (OTHER_REVISION, True))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "blocked"
    assert result["next_gate"] == "operator-checkout"
    assert result["next_command"] is None
    assert OTHER_REVISION in result["message"]
    assert REVISION in result["message"]


def test_non_main_checkout_suppresses_executable_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))
    monkeypatch.setattr(status, "_git_checkout_branch", lambda root: "feature/stale")

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "blocked"
    assert result["next_gate"] == "operator-checkout"
    assert result["next_command"] is None
    assert "main" in result["message"]
    assert "feature/stale" in result["message"]


def test_missing_appearance_pack_routes_to_exact_p0_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["next_gate"] == "appearance_epoch_visual_review"
    assert "prepare-photoreal-v2-appearance-epoch-review.ps1" in result["next_command"]


def test_missing_teacher_input_is_human_review_gate_not_auto_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    _appearance(teacher)
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "human-review-required"
    assert result["next_gate"] == "appearance_epoch_human_review"
    assert "continue-photoreal-v2-teacher.ps1" in result["next_command"]
    assert "-ApproveHumanReview" not in result["next_command"]


def test_static_teacher_never_guesses_environment_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    _appearance(teacher)
    _write_json(teacher / "teacher-input.json")
    monkeypatch.setattr(status, "validate_teacher_input_document", lambda value: dict(value))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "operator-input-required"
    assert result["next_gate"] == "static_teacher_benchmark"
    assert result["next_command"] is None
    assert set(result["missing_operator_inputs"]) == {
        "asset_root",
        "reference_model_root",
        "smplx_gender",
        "camera_mode",
    }


def test_p1_review_command_contains_no_human_pass_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    appearance = _appearance(teacher)
    _teacher_ready(teacher)
    monkeypatch.setattr(status, "validate_teacher_input_document", lambda value: dict(value))
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "human-review-required"
    assert result["next_gate"] == "p1_static_teacher_review"
    assert "run-photoreal-v2-p1-review.ps1" in result["next_command"]
    assert str(appearance.resolve()) in result["next_command"]
    assert "-ConfirmLikenessReview" not in result["next_command"]
    assert "-Decision" not in result["next_command"]


def test_p1_fail_blocks_p2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _write_json(p0 / "P0_DOWNSTREAM_READINESS.json")
    _appearance(teacher)
    _teacher_ready(teacher)
    monkeypatch.setattr(status, "validate_teacher_input_document", lambda value: dict(value))
    _write_json(teacher / "p1-static-teacher-review" / "p1-likeness-review.json")
    _write_json(
        teacher / "p1-static-teacher-review" / "likeness-review" / "p1-likeness-review-manifest.json"
    )
    monkeypatch.setattr(
        status,
        "validate_likeness_review_pack",
        lambda output_root: {"p1_likeness_review_manifest_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        status,
        "validate_likeness_review_receipt",
        lambda receipt, review_manifest=None: {
            "p1_static_teacher_status": "fail",
            "p2_animation_authorized": False,
        },
    )

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "blocked"
    assert result["next_gate"] == "p1_static_teacher_review"
    assert result["next_command"] is None


def test_stale_p2_plan_cannot_follow_current_p1_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2 = teacher / "p2-animated-teacher"
    _write_json(p2 / "p2-animation-plan.json")
    stale = _p2_plan_authority()
    stale["p1_likeness_review_sha256"] = "9" * 64
    monkeypatch.setattr(
        status,
        "validate_p2_animation_plan",
        lambda value: dict(stale),
    )

    with pytest.raises(
        status.PhotorealV2OperatorStatusError,
        match="targets stale P1 authority",
    ):
        status.inspect_photoreal_v2_status(
            p0_root=p0,
            teacher_work_root=teacher,
            operator_root=repo,
        )


def test_p2_source_selection_is_explicit_human_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2 = teacher / "p2-animated-teacher"
    _write_json(p2 / "p2-animation-plan.json")
    monkeypatch.setattr(status, "validate_p2_animation_plan", lambda value: _p2_plan_authority())
    _write_json(p2 / "motion-evidence" / "p2-motion-evidence-handoff.json")
    _write_json(p2 / "motion-evidence" / "private-motion-source-index.json")
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "human-review-required"
    assert result["next_gate"] == "p2_motion_source_selection"
    assert "record-photoreal-v2-p2-motion-selection.ps1" in result["next_command"]
    assert "-ApproveHumanSelection" not in result["next_command"]


def test_multi_driver_selection_can_be_routed_with_explicit_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    _trust_p2_materialized_chain(monkeypatch)
    p2 = teacher / "p2-animated-teacher"
    _write_json(p2 / "p2-animation-plan.json")
    monkeypatch.setattr(status, "validate_p2_animation_plan", lambda value: _p2_plan_authority())
    _write_json(p2 / "motion-evidence" / "p2-motion-evidence-handoff.json")
    _write_json(p2 / "motion-evidence" / "private-motion-source-index.json")
    _write_json(p2 / "p2-motion-source-selection.json")
    monkeypatch.setattr(
        status,
        "_selected_motion_refs",
        lambda *args, **kwargs: (["driver-a", "driver-b"], ["src-heldout"]),
    )
    _write_json(p2 / "motion-input" / "p2-motion-input-plan.json")
    _write_json(p2 / "motion-input" / "p2-motion-normalization-selection.json")
    _write_json(p2 / "motion-input" / "p2-motion-window-selection.json")
    _write_json(p2 / "motion-preparation" / "motion-preparation-receipt.json")
    _write_json(
        p2
        / "animation-input"
        / "exavatar-identity"
        / "p2-exavatar-animation-identity.json"
    )
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    missing = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )
    assert missing["state"] == "operator-input-required"
    assert missing["missing_operator_inputs"] == ["single_motion_driver_source_ref"]

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
        single_motion_driver_source_ref="driver-b",
    )

    assert result["next_gate"] == "p2_animation_execution_input"
    assert result["next_command"] is not None
    assert "-MotionDriverSourceRef 'driver-b'" in result["next_command"]
    assert "driver-a" not in result["next_command"]


def test_multi_driver_router_rejects_unapproved_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    _trust_p2_materialized_chain(monkeypatch)
    p2 = teacher / "p2-animated-teacher"
    _write_json(p2 / "p2-animation-plan.json")
    monkeypatch.setattr(status, "validate_p2_animation_plan", lambda value: _p2_plan_authority())
    _write_json(p2 / "motion-evidence" / "p2-motion-evidence-handoff.json")
    _write_json(p2 / "motion-evidence" / "private-motion-source-index.json")
    _write_json(p2 / "p2-motion-source-selection.json")
    monkeypatch.setattr(
        status,
        "_selected_motion_refs",
        lambda *args, **kwargs: (["driver-a", "driver-b"], ["src-heldout"]),
    )
    _write_json(p2 / "motion-input" / "p2-motion-input-plan.json")
    _write_json(p2 / "motion-input" / "p2-motion-normalization-selection.json")
    _write_json(p2 / "motion-input" / "p2-motion-window-selection.json")
    _write_json(p2 / "motion-preparation" / "motion-preparation-receipt.json")
    _write_json(
        p2
        / "animation-input"
        / "exavatar-identity"
        / "p2-exavatar-animation-identity.json"
    )

    with pytest.raises(
        status.PhotorealV2OperatorStatusError,
        match="not one of the human-approved TRAIN drivers",
    ):
        status.inspect_photoreal_v2_status(
            p0_root=p0,
            teacher_work_root=teacher,
            operator_root=repo,
            single_motion_driver_source_ref="driver-x",
        )


def test_p2_human_decisions_are_never_synthesized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2, _ = _p2_intermediate_ready(monkeypatch, teacher)

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "human-review-required"
    assert result["next_gate"] == "p2_animated_human_review"
    assert result["next_command"] is None
    assert "PASS/FAIL" in result["message"]


def test_existing_p2_execution_input_is_strict_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    _p2_intermediate_ready(monkeypatch, teacher)

    def reject_execution(value: dict) -> dict:
        raise status.PhotorealP2ExAvatarAnimationExecutionInputError("fixture drift")

    monkeypatch.setattr(
        status,
        "validate_exavatar_animation_execution_input",
        reject_execution,
    )

    with pytest.raises(
        status.PhotorealV2OperatorStatusError,
        match="execution-input strict readback failed",
    ):
        status.inspect_photoreal_v2_status(
            p0_root=p0,
            teacher_work_root=teacher,
            operator_root=repo,
        )


def test_heldout_input_cannot_cross_source_workspaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    _p2_intermediate_ready(monkeypatch, teacher)
    monkeypatch.setattr(
        status,
        "validate_heldout_evaluation_input",
        lambda value: {"held_out_motion": {"source_ref": "different-heldout"}},
    )

    with pytest.raises(
        status.PhotorealV2OperatorStatusError,
        match="source reference does not match its workspace",
    ):
        status.inspect_photoreal_v2_status(
            p0_root=p0,
            teacher_work_root=teacher,
            operator_root=repo,
        )


def test_p2_pass_requires_explicit_p3_target_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2, _ = _p2_intermediate_ready(monkeypatch, teacher)
    _write_json(p2 / "animated-review" / "p2-heldout-animated-human-review.json")
    monkeypatch.setattr(
        status,
        "validate_animated_human_review_receipt",
        lambda receipt, review_manifest=None: _p2_pass_review(),
    )

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "operator-input-required"
    assert result["next_gate"] == "p3_device_distillation_plan"
    assert result["missing_operator_inputs"] == ["p3_target_profile"]


def _p3_lineage() -> dict[str, str]:
    return {
        "performer_id": PERFORMER,
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "target_profile_sha256": "6" * 64,
    }


def test_p3_photoreal_acceptance_still_keeps_production_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2, _ = _p2_intermediate_ready(monkeypatch, teacher)
    _write_json(p2 / "animated-review" / "p2-heldout-animated-human-review.json")
    monkeypatch.setattr(
        status,
        "validate_animated_human_review_receipt",
        lambda receipt, review_manifest=None: _p2_pass_review(),
    )
    p3 = teacher / "p3-device-distillation"
    _write_json(p3 / "p3-device-distillation-plan.json")
    lineage = _p3_lineage()
    monkeypatch.setattr(
        status,
        "validate_p3_device_distillation_plan",
        lambda value: dict(lineage),
    )
    physical = (
        p3
        / "quest2-full-software"
        / "continuation"
        / "runtime-review"
        / "p3-physical-runtime-review.json"
    )
    _write_json(physical)
    monkeypatch.setattr(
        status,
        "validate_physical_runtime_review_receipt",
        lambda value: {
            **lineage,
            "runtime_review_status": "pass",
            "runtime_acceptance_authority": True,
            "photoreal_acceptance_authority": True,
            "production_activation": False,
        },
    )

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "p3-complete"
    assert result["next_gate"] == "photoreal_person_binding"
    assert result["p3_photoreal_acceptance_authority"] is True
    assert result["production_activation"] is False
    assert result["next_command"] is None


def test_stale_p3_plan_cannot_follow_current_p2_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2, _ = _p2_intermediate_ready(monkeypatch, teacher)
    _write_json(p2 / "animated-review" / "p2-heldout-animated-human-review.json")
    monkeypatch.setattr(
        status,
        "validate_animated_human_review_receipt",
        lambda receipt, review_manifest=None: _p2_pass_review(),
    )
    p3 = teacher / "p3-device-distillation"
    _write_json(p3 / "p3-device-distillation-plan.json")
    stale = _p3_lineage()
    stale["p2_animated_human_review_sha256"] = "9" * 64
    monkeypatch.setattr(
        status,
        "validate_p3_device_distillation_plan",
        lambda value: dict(stale),
    )

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "blocked"
    assert result["next_gate"] == "p3_lineage"
    assert result["next_command"] is None
    assert "p2_animated_human_review_sha256" in result["message"]


def test_stale_p3_physical_receipt_cannot_accept_replaced_current_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p0, repo, teacher = _workspace(tmp_path)
    _trust_p0(monkeypatch)
    _base_ready(monkeypatch, p0, teacher)
    p2, _ = _p2_intermediate_ready(monkeypatch, teacher)
    _write_json(p2 / "animated-review" / "p2-heldout-animated-human-review.json")
    monkeypatch.setattr(
        status,
        "validate_animated_human_review_receipt",
        lambda receipt, review_manifest=None: _p2_pass_review(),
    )
    p3 = teacher / "p3-device-distillation"
    _write_json(p3 / "p3-device-distillation-plan.json")
    current = _p3_lineage()
    monkeypatch.setattr(
        status,
        "validate_p3_device_distillation_plan",
        lambda value: dict(current),
    )
    physical = (
        p3
        / "quest2-full-software"
        / "continuation"
        / "runtime-review"
        / "p3-physical-runtime-review.json"
    )
    _write_json(physical)
    stale = dict(current)
    stale["p3_device_distillation_plan_sha256"] = "9" * 64
    monkeypatch.setattr(
        status,
        "validate_physical_runtime_review_receipt",
        lambda value: {
            **stale,
            "runtime_review_status": "pass",
            "runtime_acceptance_authority": True,
            "photoreal_acceptance_authority": True,
            "production_activation": False,
        },
    )

    result = status.inspect_photoreal_v2_status(
        p0_root=p0,
        teacher_work_root=teacher,
        operator_root=repo,
    )

    assert result["state"] == "blocked"
    assert result["next_gate"] == "p3_lineage"
    assert result["next_command"] is None
    assert result["p3_photoreal_acceptance_authority"] is False
    assert "p3_device_distillation_plan_sha256" in result["message"]


def test_cli_uses_blocked_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        status_cli,
        "inspect_photoreal_v2_status",
        lambda **kwargs: {"state": "blocked", "read_only": True},
    )
    code = status_cli.main(["--p0-root", "p0"])
    assert code == 3
    assert json.loads(capsys.readouterr().out)["state"] == "blocked"


def test_cli_forwards_explicit_motion_driver(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def fake_status(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"state": "required", "read_only": True}

    monkeypatch.setattr(status_cli, "inspect_photoreal_v2_status", fake_status)
    code = status_cli.main(
        [
            "--p0-root",
            "p0",
            "--single-motion-driver-source-ref",
            "driver-b",
        ]
    )

    assert code == 0
    assert seen["single_motion_driver_source_ref"] == "driver-b"
    assert json.loads(capsys.readouterr().out)["read_only"] is True


def test_powershell_wrapper_is_status_only() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "photoreal-v2-status.ps1").read_text(encoding="utf-8")
    assert "bodyrig.photoreal_v2_operator_status_cli" in source
    assert '"--operator-root", $repoRoot' in source
    assert "$env:PYTHONPATH = $repoRoot" in source
    assert "--single-motion-driver-source-ref" in source
    for mutation in (
        "Set-Content",
        "Out-File",
        "New-Item",
        "Move-Item",
        "Remove-Item",
        "Copy-Item",
    ):
        assert mutation not in source
