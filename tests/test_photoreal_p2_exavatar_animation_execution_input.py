from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_exavatar_animation_execution_input as execution_input
from bodyrig.photoreal_p2_exavatar_animation_execution_input import (
    PhotorealP2ExAvatarAnimationExecutionInputError,
    build_exavatar_animation_execution_input,
    validate_exavatar_animation_execution_input,
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact(path: Path, payload: bytes, *, relative: str) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "relative_path": relative,
        "size_bytes": len(payload),
        "sha256": _sha_bytes(payload),
    }


def _plan() -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": 123,
            "sha256": "3" * 64,
        },
    }


def _identity(root: Path) -> dict[str, object]:
    values = []
    for kind, filename, payload in (
        ("shape-param", "shape_param.json", b"[1]\n"),
        ("face-offset", "face_offset.json", b"[[0,0,0]]\n"),
        ("joint-offset", "joint_offset.json", b"[[0,0,0]]\n"),
        ("locator-offset", "locator_offset.json", b"[[0,0,0]]\n"),
    ):
        path = root / "identity" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        values.append(
            {
                "kind": kind,
                "source_relative_path": f"smplx_optimized/{filename}",
                "export_relative_path": f"identity/{filename}",
                "size_bytes": len(payload),
                "sha256": _sha_bytes(payload),
            }
        )
    receipt = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "teacher_checkpoint": _plan()["teacher_checkpoint"],
        "exavatar_workspace_sha256": "6" * 64,
        "exavatar_preprocess_state_sha256": "7" * 64,
        "exavatar_subject_id": "bodyrig-42",
        "identity_artifacts": values,
        "identity_artifact_count": 4,
        "p2_animation_identity_input_ready": True,
        "p2_animation_execution_authorized": False,
        "p2_exavatar_animation_identity_sha256": "4" * 64,
    }
    return receipt


def _motion(root: Path) -> dict[str, object]:
    train_ref = "src-train"
    eval_ref = "src-eval"

    def task(ref: str, split: str, role: str, base_id: int) -> dict[str, object]:
        motion = f"tasks/{ref}/motion"
        artifacts = [
            _artifact(
                root / motion / "frames" / f"{base_id}.png",
                f"frame-{ref}".encode(),
                relative=f"{motion}/frames/{base_id}.png",
            ),
            _artifact(
                root / motion / "cam_params" / f"{base_id}.json",
                b'{"R":[],"t":[],"focal":[],"princpt":[]}\n',
                relative=f"{motion}/cam_params/{base_id}.json",
            ),
            _artifact(
                root / motion / "smplx_optimized" / "smplx_params_smoothed" / f"{base_id}.json",
                b'{"root_pose":[],"body_pose":[],"jaw_pose":[],"leye_pose":[],"reye_pose":[],"lhand_pose":[],"rhand_pose":[],"expr":[],"trans":[]}\n',
                relative=f"{motion}/smplx_optimized/smplx_params_smoothed/{base_id}.json",
            ),
        ]
        return {
            "source_ref": ref,
            "split": split,
            "role": role,
            "normalization_action": "preserve-flat-mono-video",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": f"obs-{ref}",
            "anchor_frame_sha256": ("a" if split == "train" else "b") * 64,
            "window_start_seconds": 1.0,
            "window_end_seconds": 3.0,
            "window_duration_seconds": 2.0,
            "motion_path_relative": motion,
            "frame_count": 1,
            "source_media_rehash_performed": False,
            "artifacts": artifacts,
        }

    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "task_results": [
            task(train_ref, "train", "motion-driver", 10),
            task(eval_ref, "evaluation", "held-out-motion-validation", 20),
        ],
        "p2_animation_execution_authorized": True,
        "p2_motion_preparation_receipt_sha256": "5" * 64,
    }


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, object],
    identity: dict[str, object],
    motion: dict[str, object],
) -> None:
    monkeypatch.setattr(execution_input, "validate_p2_animation_plan", lambda value: plan)
    monkeypatch.setattr(
        execution_input,
        "validate_exavatar_animation_identity",
        lambda value, output_root: identity,
    )
    monkeypatch.setattr(
        execution_input,
        "validate_motion_preparation_receipt",
        lambda value: motion,
    )


def test_execution_input_binds_train_driver_and_excludes_heldout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    plan = _plan()
    identity = _identity(identity_root)
    motion = _motion(motion_root)
    _trust(monkeypatch, plan, identity, motion)

    result = build_exavatar_animation_execution_input(
        plan,
        identity,
        motion,
        identity_output_root=identity_root,
        motion_output_root=motion_root,
        motion_driver_source_ref="src-train",
    )

    assert result["motion_driver"]["source_ref"] == "src-train"
    assert result["motion_driver"]["split"] == "train"
    assert result["motion_driver"]["role"] == "motion-driver"
    assert result["motion_driver"]["frame_ids"] == [10]
    assert result["held_out_evaluation_disclosed_to_animation"] is False
    assert result["train_motion_driver_only"] is True
    assert result["animation_started"] is False
    assert result["p2_animation_execution_authorized"] is True
    serialized = json.dumps(result, sort_keys=True)
    assert "src-eval" not in serialized
    assert "/20." not in serialized


def test_execution_input_rejects_heldout_as_animation_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    plan = _plan()
    identity = _identity(identity_root)
    motion = _motion(motion_root)
    _trust(monkeypatch, plan, identity, motion)

    with pytest.raises(
        PhotorealP2ExAvatarAnimationExecutionInputError,
        match="TRAIN motion-driver",
    ):
        build_exavatar_animation_execution_input(
            plan,
            identity,
            motion,
            identity_output_root=identity_root,
            motion_output_root=motion_root,
            motion_driver_source_ref="src-eval",
        )


def test_execution_input_rejects_motion_artifact_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    plan = _plan()
    identity = _identity(identity_root)
    motion = _motion(motion_root)
    _trust(monkeypatch, plan, identity, motion)
    path = motion_root / "tasks" / "src-train" / "motion" / "frames" / "10.png"
    path.write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2ExAvatarAnimationExecutionInputError,
        match="size/path drifted|bytes drifted",
    ):
        build_exavatar_animation_execution_input(
            plan,
            identity,
            motion,
            identity_output_root=identity_root,
            motion_output_root=motion_root,
            motion_driver_source_ref="src-train",
        )


def test_execution_input_rejects_resealed_downstream_authority() -> None:
    value = {
        "format": execution_input.FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_identity_sha256": "4" * 64,
        "p2_motion_preparation_receipt_sha256": "5" * 64,
        "exavatar_workspace_sha256": "6" * 64,
        "exavatar_preprocess_state_sha256": "7" * 64,
        "exavatar_upstream_commit": execution_input.PINNED_UPSTREAM_COMMIT,
        "exavatar_animation_adapter": execution_input.P2_ANIMATION_ADAPTER,
        "exavatar_animation_script": execution_input.UPSTREAM_ANIMATION_SCRIPT,
        "exavatar_subject_id": "bodyrig-42",
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": 123,
            "sha256": "3" * 64,
        },
        "identity_artifacts": [
            {
                "kind": kind,
                "source_relative_path": f"smplx_optimized/{filename}",
                "export_relative_path": f"identity/{filename}",
                "size_bytes": 1,
                "sha256": "6" * 64,
            }
            for kind, filename in (
                ("shape-param", "shape_param.json"),
                ("face-offset", "face_offset.json"),
                ("joint-offset", "joint_offset.json"),
                ("locator-offset", "locator_offset.json"),
            )
        ],
        "identity_artifact_count": 4,
        "motion_driver": {
            "source_ref": "src-train",
            "split": "train",
            "role": "motion-driver",
            "normalization_action": "preserve-flat-mono-video",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": "obs-train",
            "anchor_frame_sha256": "a" * 64,
            "window_start_seconds": 1.0,
            "window_end_seconds": 3.0,
            "window_duration_seconds": 2.0,
            "motion_path_relative": "tasks/src-train/motion",
            "frame_count": 1,
            "frame_ids": [10],
            "artifacts": [
                {
                    "relative_path": "tasks/src-train/motion/frames/10.png",
                    "size_bytes": 1,
                    "sha256": "7" * 64,
                },
                {
                    "relative_path": "tasks/src-train/motion/cam_params/10.json",
                    "size_bytes": 1,
                    "sha256": "8" * 64,
                },
                {
                    "relative_path": "tasks/src-train/motion/smplx_optimized/smplx_params_smoothed/10.json",
                    "size_bytes": 1,
                    "sha256": "9" * 64,
                },
            ],
        },
        "identity_artifact_bytes_reverified": True,
        "motion_driver_artifact_bytes_reverified": True,
        "held_out_evaluation_disclosed_to_animation": True,
        "train_motion_driver_only": True,
        "animation_started": False,
        "p2_animation_execution_authorized": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p2_exavatar_animation_execution_input_sha256"] = execution_input._digest(
        value,
        omit="p2_exavatar_animation_execution_input_sha256",
    )

    with pytest.raises(
        PhotorealP2ExAvatarAnimationExecutionInputError,
        match="held_out_evaluation_disclosed_to_animation",
    ):
        validate_exavatar_animation_execution_input(value)


def test_execution_input_rejects_boolean_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    plan = _plan()
    identity = _identity(identity_root)
    motion = _motion(motion_root)
    _trust(monkeypatch, plan, identity, motion)
    value = build_exavatar_animation_execution_input(
        plan,
        identity,
        motion,
        identity_output_root=identity_root,
        motion_output_root=motion_root,
        motion_driver_source_ref="src-train",
    )
    value["version"] = True
    value["p2_exavatar_animation_execution_input_sha256"] = execution_input._digest(
        value,
        omit="p2_exavatar_animation_execution_input_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarAnimationExecutionInputError,
        match="format/version mismatch",
    ):
        validate_exavatar_animation_execution_input(value)
