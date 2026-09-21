from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_exavatar_animation_identity as identity
from bodyrig.photoreal_p2_exavatar_animation_identity import (
    PhotorealP2ExAvatarAnimationIdentityError,
    build_exavatar_animation_identity,
    validate_exavatar_animation_identity,
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(path: Path, value: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {
        "path": path.resolve().as_posix(),
        "size_bytes": len(value),
        "sha256": _sha_bytes(value),
    }


def _plan(checkpoint: Path) -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": checkpoint.stat().st_size,
            "sha256": _sha_bytes(checkpoint.read_bytes()),
        },
    }


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    workspace = tmp_path / "workspace"
    dataset = workspace / "dataset" / "bodyrig-42"
    teacher = tmp_path / "teacher-output"
    checkpoint = teacher / "checkpoint" / "snapshot_4.pth"
    _write(checkpoint, b"accepted-checkpoint")

    fit_records: list[dict[str, object]] = []
    for name, payload in (
        ("shape_param.json", b"[1,2,3]\n"),
        ("face_offset.json", b"[[0,0,0]]\n"),
        ("joint_offset.json", b"[[1,0,0]]\n"),
        ("locator_offset.json", b"[[0,1,0]]\n"),
    ):
        fit_records.append(
            _write(dataset / "smplx_optimized" / name, payload)
        )

    workspace_receipt: dict[str, object] = {
        "format": "bodyrig-photoreal-exavatar-workspace",
        "version": 1,
        "performer_id": "42",
        "subject_id": "bodyrig-42",
        "selected_epoch_id": "epoch-a",
        "benchmark_plan_sha256": "3" * 64,
        "teacher_input_sha256": "1" * 64,
        "materialization_receipt_sha256": "4" * 64,
        "strict_preflight_sha256": "5" * 64,
        "upstream_commit": identity.PINNED_UPSTREAM_COMMIT,
        "repository_commits": {"ExAvatar_RELEASE": identity.PINNED_UPSTREAM_COMMIT},
        "smplx_gender": "female",
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "dataset": "Custom",
        "fitting_config_sha256": "6" * 64,
        "avatar_config_patch": {},
        "injected_patch_files": [],
        "linked_assets": [],
        "frame_count": 4,
        "working_dataset_relative_path": "dataset/bodyrig-42",
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "dependency_root_modified": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    workspace_receipt["workspace_sha256"] = identity._digest(
        workspace_receipt,
        omit="workspace_sha256",
    )
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "workspace-receipt.json").write_text(
        json.dumps(workspace_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    state: dict[str, object] = {
        "format": "bodyrig-photoreal-exavatar-preprocess-state",
        "version": 1,
        "preprocess_plan_sha256": "7" * 64,
        "workspace_sha256": workspace_receipt["workspace_sha256"],
        "completed_stages": [
            {"name": "camera", "outputs": []},
            {"name": "deca-flame", "outputs": []},
            {"name": "hand4whole-smplx-init", "outputs": []},
            {"name": "wholebody-keypoints", "outputs": []},
            {"name": "smplx-fit", "outputs": fit_records},
            {"name": "face-texture-unwrap", "outputs": []},
            {"name": "smplx-smooth", "outputs": []},
            {"name": "sam-masks", "outputs": []},
            {"name": "background-depth", "outputs": []},
        ],
        "preprocessing_complete": True,
        "teacher_training_authorized_by_preprocessing": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }
    state["preprocess_state_sha256"] = identity._digest(
        state,
        omit="preprocess_state_sha256",
    )
    (workspace / "preprocess-state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace, dataset, teacher, _plan(checkpoint)


def _trust_plan(monkeypatch: pytest.MonkeyPatch, plan: dict[str, object]) -> None:
    monkeypatch.setattr(
        identity,
        "validate_p2_animation_plan",
        lambda value: plan if value is plan else dict(value),
    )


def test_identity_export_binds_checkpoint_and_four_preprocess_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    output = tmp_path / "identity-export"

    receipt = build_exavatar_animation_identity(
        plan,
        exavatar_workspace_root=workspace,
        teacher_output_root=teacher,
        output_root=output,
    )

    assert receipt["identity_artifact_count"] == 4
    assert receipt["teacher_checkpoint_bytes_reverified"] is True
    assert receipt["identity_bytes_reverified_against_preprocess_state"] is True
    assert receipt["source_media_rehash_performed"] is False
    assert receipt["p2_animation_identity_input_ready"] is True
    assert receipt["p2_animation_execution_authorized"] is False
    assert receipt["p2_animated_teacher_acceptance_authority"] is False
    assert receipt["production_activation"] is False
    assert {item["kind"] for item in receipt["identity_artifacts"]} == {
        "shape-param",
        "face-offset",
        "joint-offset",
        "locator-offset",
    }
    assert {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    } == {
        "identity/shape_param.json",
        "identity/face_offset.json",
        "identity/joint_offset.json",
        "identity/locator_offset.json",
        "p2-exavatar-animation-identity.json",
    }


def test_identity_export_rejects_checkpoint_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    (teacher / "checkpoint" / "snapshot_4.pth").write_bytes(b"substituted")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="checkpoint size/path drifted|checkpoint bytes drifted",
    ):
        build_exavatar_animation_identity(
            plan,
            exavatar_workspace_root=workspace,
            teacher_output_root=teacher,
            output_root=tmp_path / "identity-export",
        )


def test_identity_export_rejects_preprocess_bound_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    (dataset / "smplx_optimized" / "joint_offset.json").write_bytes(
        b"[[999,999,999]]\n"
    )

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="identity source size/path drifted|identity source bytes drifted",
    ):
        build_exavatar_animation_identity(
            plan,
            exavatar_workspace_root=workspace,
            teacher_output_root=teacher,
            output_root=tmp_path / "identity-export",
        )


def test_identity_export_rejects_preprocess_state_reseal_with_substituted_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    state_path = workspace / "preprocess-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    stage = next(
        item for item in state["completed_stages"] if item["name"] == "smplx-fit"
    )
    stage["outputs"][0]["sha256"] = "9" * 64
    state["preprocess_state_sha256"] = identity._digest(
        state,
        omit="preprocess_state_sha256",
    )
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="identity source bytes drifted since preprocessing",
    ):
        build_exavatar_animation_identity(
            plan,
            exavatar_workspace_root=workspace,
            teacher_output_root=teacher,
            output_root=tmp_path / "identity-export",
        )


def test_identity_receipt_rejects_resealed_execution_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    output = tmp_path / "identity-export"
    receipt = build_exavatar_animation_identity(
        plan,
        exavatar_workspace_root=workspace,
        teacher_output_root=teacher,
        output_root=output,
    )
    receipt["p2_animation_execution_authorized"] = True
    receipt["p2_exavatar_animation_identity_sha256"] = identity._digest(
        receipt,
        omit="p2_exavatar_animation_identity_sha256",
    )

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="authority mismatch: p2_animation_execution_authorized",
    ):
        validate_exavatar_animation_identity(receipt, output_root=output)


def test_identity_receipt_rejects_extra_export_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    output = tmp_path / "identity-export"
    receipt = build_exavatar_animation_identity(
        plan,
        exavatar_workspace_root=workspace,
        teacher_output_root=teacher,
        output_root=output,
    )
    (output / "identity" / "hidden.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="output file universe mismatch",
    ):
        validate_exavatar_animation_identity(receipt, output_root=output)


def test_identity_export_rejects_boolean_workspace_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    path = workspace / "workspace-receipt.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = True
    value["workspace_sha256"] = identity._digest(value, omit="workspace_sha256")
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="format/version mismatch",
    ):
        build_exavatar_animation_identity(
            plan,
            exavatar_workspace_root=workspace,
            teacher_output_root=teacher,
            output_root=tmp_path / "identity-export",
        )


def test_identity_receipt_rejects_export_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _dataset, teacher, plan = _workspace(tmp_path)
    _trust_plan(monkeypatch, plan)
    output = tmp_path / "identity-export"
    receipt = build_exavatar_animation_identity(
        plan,
        exavatar_workspace_root=workspace,
        teacher_output_root=teacher,
        output_root=output,
    )
    exported = output / "identity" / "face_offset.json"
    exported.write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationIdentityError,
        match="exported artifact size/path mismatch|exported artifact bytes drifted",
    ):
        validate_exavatar_animation_identity(receipt, output_root=output)
