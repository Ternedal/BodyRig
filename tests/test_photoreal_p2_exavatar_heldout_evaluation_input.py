from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_exavatar_heldout_evaluation_input as heldout
from bodyrig.photoreal_p2_exavatar_heldout_evaluation_input import (
    PhotorealP2ExAvatarHeldoutEvaluationInputError,
    build_heldout_evaluation_input,
    validate_heldout_evaluation_input,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"size_bytes": len(payload), "sha256": _sha(payload)}


def _artifacts(tmp_path: Path) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    Path,
    Path,
    Path,
]:
    identity_root = tmp_path / "identity"
    teacher_root = tmp_path / "teacher"
    motion_root = tmp_path / "motion"

    checkpoint = _write(
        teacher_root / "checkpoint" / "snapshot_4.pth",
        b"checkpoint",
    )
    identity_artifacts = []
    for kind, filename, payload in (
        ("shape-param", "shape_param.json", b"[1]\n"),
        ("face-offset", "face_offset.json", b"[[0,0,0]]\n"),
        ("joint-offset", "joint_offset.json", b"[[0,0,0]]\n"),
        ("locator-offset", "locator_offset.json", b"[[0,0,0]]\n"),
    ):
        record = _write(identity_root / "identity" / filename, payload)
        identity_artifacts.append(
            {
                "kind": kind,
                "source_relative_path": f"smplx_optimized/{filename}",
                "export_relative_path": f"identity/{filename}",
                **record,
            }
        )

    def motion_task(
        ref: str,
        *,
        split: str,
        role: str,
        frame_id: int,
    ) -> dict[str, object]:
        prefix = f"tasks/{ref}/motion"
        artifacts = []
        for relative, payload in (
            (f"{prefix}/frames/{frame_id}.png", f"frame-{ref}".encode()),
            (f"{prefix}/cam_params/{frame_id}.json", b"{}\n"),
            (
                f"{prefix}/smplx_optimized/smplx_params_smoothed/{frame_id}.json",
                b"{}\n",
            ),
        ):
            artifacts.append(
                {"relative_path": relative, **_write(motion_root / relative, payload)}
            )
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
            "motion_path_relative": prefix,
            "frame_count": 1,
            "source_media_rehash_performed": False,
            "artifacts": artifacts,
        }

    execution_input = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "exavatar_workspace_sha256": "4" * 64,
        "exavatar_preprocess_state_sha256": "5" * 64,
        "exavatar_subject_id": "bodyrig-42",
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            **checkpoint,
        },
        "identity_artifacts": identity_artifacts,
    }
    train_receipt = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_exavatar_animation_execution_receipt_sha256": "6" * 64,
        "consumed_checkpoint_sha256": checkpoint["sha256"],
        "consumed_identity_artifacts": [
            {"kind": item["kind"], "sha256": item["sha256"]}
            for item in identity_artifacts
        ],
        "motion_driver_source_ref": "src-train",
        "animation_complete": True,
        "inference_only": True,
        "teacher_training_performed": False,
        "checkpoint_mutation_performed": False,
        "held_out_evaluation_disclosed": False,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "production_activation": False,
    }
    motion_receipt = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_motion_preparation_receipt_sha256": "7" * 64,
        "task_results": [
            motion_task(
                "src-train",
                split="train",
                role="motion-driver",
                frame_id=10,
            ),
            motion_task(
                "src-eval",
                split="evaluation",
                role="held-out-motion-validation",
                frame_id=20,
            ),
        ],
    }
    return (
        execution_input,
        train_receipt,
        motion_receipt,
        identity_root,
        teacher_root,
        motion_root,
    )


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    execution_input: dict[str, object],
    train_receipt: dict[str, object],
    motion_receipt: dict[str, object],
) -> None:
    monkeypatch.setattr(
        heldout,
        "validate_exavatar_animation_execution_input",
        lambda value: execution_input,
    )
    monkeypatch.setattr(
        heldout,
        "validate_animation_execution_receipt",
        lambda value: train_receipt,
    )
    monkeypatch.setattr(
        heldout,
        "validate_motion_preparation_receipt",
        lambda value: motion_receipt,
    )


def test_heldout_input_opens_only_after_frozen_train_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)

    result = build_heldout_evaluation_input(
        execution_input,
        train_receipt,
        motion_receipt,
        identity_root=identity_root,
        teacher_output_root=teacher_root,
        motion_output_root=motion_root,
        heldout_source_ref="src-eval",
    )

    assert result["held_out_motion"]["source_ref"] == "src-eval"
    assert result["held_out_motion"]["split"] == "evaluation"
    assert result["held_out_motion"]["role"] == "held-out-motion-validation"
    assert result["held_out_motion"]["frame_ids"] == [20]
    assert result["train_animation_complete"] is True
    assert result["train_animation_inference_only"] is True
    assert result["held_out_evaluation_disclosed_to_animation"] is True
    assert result["held_out_disclosure_purpose"] == heldout.DISCLOSURE_PURPOSE
    assert result["teacher_training_authorized"] is False
    assert result["checkpoint_mutation_authorized"] is False
    assert result["p2_heldout_animation_evaluation_authorized"] is True
    assert result["p2_animated_teacher_acceptance_authority"] is False
    assert result["production_activation"] is False
    serialized = str(result)
    assert "tasks/src-train/motion/frames/10.png" not in serialized


def test_heldout_input_rejects_train_driver_as_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)

    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="cannot reuse the TRAIN motion driver",
    ):
        build_heldout_evaluation_input(
            execution_input,
            train_receipt,
            motion_receipt,
            identity_root=identity_root,
            teacher_output_root=teacher_root,
            motion_output_root=motion_root,
            heldout_source_ref="src-train",
        )


def test_heldout_input_rejects_different_train_identity_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    train_receipt["consumed_identity_artifacts"][0]["sha256"] = "f" * 64
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)

    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="different identity bytes",
    ):
        build_heldout_evaluation_input(
            execution_input,
            train_receipt,
            motion_receipt,
            identity_root=identity_root,
            teacher_output_root=teacher_root,
            motion_output_root=motion_root,
            heldout_source_ref="src-eval",
        )


def test_heldout_input_rejects_non_frozen_train_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    train_receipt["checkpoint_mutation_performed"] = True
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)

    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="checkpoint_mutation_performed",
    ):
        build_heldout_evaluation_input(
            execution_input,
            train_receipt,
            motion_receipt,
            identity_root=identity_root,
            teacher_output_root=teacher_root,
            motion_output_root=motion_root,
            heldout_source_ref="src-eval",
        )


def test_heldout_input_rejects_evaluation_motion_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)
    (
        motion_root
        / "tasks"
        / "src-eval"
        / "motion"
        / "frames"
        / "20.png"
    ).write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="size/path drifted|bytes drifted",
    ):
        build_heldout_evaluation_input(
            execution_input,
            train_receipt,
            motion_receipt,
            identity_root=identity_root,
            teacher_output_root=teacher_root,
            motion_output_root=motion_root,
            heldout_source_ref="src-eval",
        )


def test_resealed_heldout_input_cannot_authorize_training(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)
    result = build_heldout_evaluation_input(
        execution_input,
        train_receipt,
        motion_receipt,
        identity_root=identity_root,
        teacher_output_root=teacher_root,
        motion_output_root=motion_root,
        heldout_source_ref="src-eval",
    )
    result["teacher_training_authorized"] = True
    result["p2_exavatar_heldout_evaluation_input_sha256"] = heldout._digest(
        result,
        omit="p2_exavatar_heldout_evaluation_input_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="authority mismatch: teacher_training_authorized",
    ):
        validate_heldout_evaluation_input(result)


def test_heldout_input_rejects_boolean_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _artifacts(tmp_path)
    execution_input, train_receipt, motion_receipt, identity_root, teacher_root, motion_root = values
    _trust(monkeypatch, execution_input, train_receipt, motion_receipt)
    result = build_heldout_evaluation_input(
        execution_input,
        train_receipt,
        motion_receipt,
        identity_root=identity_root,
        teacher_output_root=teacher_root,
        motion_output_root=motion_root,
        heldout_source_ref="src-eval",
    )
    result["version"] = True
    result["p2_exavatar_heldout_evaluation_input_sha256"] = heldout._digest(
        result,
        omit="p2_exavatar_heldout_evaluation_input_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationInputError,
        match="format/version mismatch",
    ):
        validate_heldout_evaluation_input(result)
