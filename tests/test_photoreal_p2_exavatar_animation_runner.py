from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_exavatar_animation_runner as runner
from bodyrig.photoreal_p2_exavatar_animation_runner import (
    PhotorealP2ExAvatarAnimationRunnerError,
    _validate_manifest,
    build_animation_execution_receipt,
    build_animation_request,
    validate_animation_execution_receipt,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "size_bytes": len(data),
        "sha256": _sha(data),
    }


def _authority(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path, Path]:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    teacher_root = tmp_path / "teacher"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    checkpoint = teacher_root / "checkpoint" / "snapshot_4.pth"
    checkpoint_record = _write(checkpoint, b"checkpoint")
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
    source_ref = "src-train"
    motion_path = f"tasks/{source_ref}/motion"
    motion_artifacts = []
    for relative, payload in (
        (f"{motion_path}/frames/10.png", b"png"),
        (f"{motion_path}/cam_params/10.json", b'{"R":[],"t":[],"focal":[],"princpt":[]}\n'),
        (
            f"{motion_path}/smplx_optimized/smplx_params_smoothed/10.json",
            b'{"root_pose":[],"body_pose":[],"jaw_pose":[],"leye_pose":[],"reye_pose":[],"lhand_pose":[],"rhand_pose":[],"expr":[],"trans":[]}\n',
        ),
    ):
        record = _write(motion_root / relative, payload)
        motion_artifacts.append({"relative_path": relative, **record})

    authority = {
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
            **checkpoint_record,
        },
        "identity_artifacts": identity_artifacts,
        "motion_driver": {
            "source_ref": source_ref,
            "split": "train",
            "role": "motion-driver",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": "obs-train",
            "anchor_frame_sha256": "6" * 64,
            "window_start_seconds": 8.0,
            "window_end_seconds": 12.0,
            "window_duration_seconds": 4.0,
            "motion_path_relative": motion_path,
            "frame_count": 1,
            "frame_ids": [10],
            "artifacts": motion_artifacts,
        },
    }
    return authority, identity_root, motion_root, teacher_root, repo_root


def _teacher_config() -> dict[str, object]:
    return {
        "format": runner.TEACHER_CONFIG_FORMAT,
        "version": 1,
        "adapter": "exavatar-benchmark",
        "revision": "teacher-transport-rev",
        "upstream_repository": runner.PINNED_UPSTREAM_REPOSITORY,
        "upstream_commit": runner.PINNED_UPSTREAM_COMMIT,
        "command": [
            "python",
            "bridge.py",
            "--distribution",
            "Ubuntu-22.04",
            "--wsl-exe",
            "wsl.exe",
            "--linux-python",
            "/opt/bodyrig-exavatar/bin/python",
            "--workspace-root",
            "/opt/bodyrig/workspace",
            "--runtime-preflight",
            "/opt/bodyrig/workspace/runtime-preflight.json",
        ],
        "timeout_seconds": 3600,
    }


def _request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], Path, Path, Path, Path]:
    authority, identity_root, motion_root, teacher_root, repo_root = _authority(tmp_path)
    adapter = tmp_path / "adapter.py"
    adapter.write_text("# adapter\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_exavatar_animation_execution_input",
        lambda value: authority,
    )
    monkeypatch.setattr(
        runner,
        "make_wsl_path_converter",
        lambda *_args: lambda value: "/linux/" + Path(value).name,
    )
    request, runtime = build_animation_request(
        authority,
        _teacher_config(),
        identity_root=identity_root,
        motion_output_root=motion_root,
        teacher_output_root=teacher_root,
        bodyrig_repo_root=repo_root,
        adapter_script=adapter,
    )
    return request, runtime, identity_root, motion_root, teacher_root, adapter


def test_animation_request_reverifies_exact_train_motion_and_identity_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, runtime, _identity, _motion, _teacher, adapter = _request(
        monkeypatch,
        tmp_path,
    )
    assert request["motion_driver"]["source_ref"] == "src-train"
    assert request["motion_driver"]["split"] == "train"
    assert request["motion_driver"]["role"] == "motion-driver"
    assert request["motion_driver"]["frame_ids"] == [10]
    assert len(request["motion_driver"]["artifacts"]) == 3
    assert len(request["identity_artifacts"]) == 4
    assert request["held_out_evaluation_disclosed"] is False
    assert request["train_motion_driver_only"] is True
    assert request["p2_animated_teacher_acceptance_authority"] is False
    assert request["production_activation"] is False
    assert request["adapter_revision"] == _sha(adapter.read_bytes())
    assert runtime["linux_python"] == "/opt/bodyrig-exavatar/bin/python"


def test_animation_request_rejects_motion_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority, identity_root, motion_root, teacher_root, repo_root = _authority(tmp_path)
    adapter = tmp_path / "adapter.py"
    adapter.write_text("# adapter\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_exavatar_animation_execution_input",
        lambda value: authority,
    )
    monkeypatch.setattr(
        runner,
        "make_wsl_path_converter",
        lambda *_args: lambda value: "/linux/" + Path(value).name,
    )
    (motion_root / "tasks" / "src-train" / "motion" / "frames" / "10.png").write_bytes(
        b"tampered"
    )
    with pytest.raises(
        PhotorealP2ExAvatarAnimationRunnerError,
        match="size/path drifted|bytes drifted",
    ):
        build_animation_request(
            authority,
            _teacher_config(),
            identity_root=identity_root,
            motion_output_root=motion_root,
            teacher_output_root=teacher_root,
            bodyrig_repo_root=repo_root,
            adapter_script=adapter,
        )


def _manifest(request: dict[str, object], output_root: Path) -> dict[str, object]:
    (output_root / "animation-manifest.json").write_text("{}\n", encoding="utf-8")
    video = output_root / "review" / "animation.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"review-video")
    return {
        "format": runner.MANIFEST_FORMAT,
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": request[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_exavatar_animation_request_sha256": request[
            "p2_exavatar_animation_request_sha256"
        ],
        "exavatar_upstream_commit": runner.PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": request["exavatar_subject_id"],
        "test_epoch": 4,
        "adapter_revision": request["adapter_revision"],
        "motion_driver_source_ref": request["motion_driver"]["source_ref"],
        "motion_frame_count": 1,
        "motion_frame_ids": [10],
        "consumed_checkpoint_sha256": request["teacher_checkpoint"]["sha256"],
        "consumed_identity_artifacts": [
            {"kind": item["kind"], "sha256": item["sha256"]}
            for item in request["identity_artifacts"]
        ],
        "consumed_motion_artifacts": [
            {"relative_path": item["relative_path"], "sha256": item["sha256"]}
            for item in request["motion_driver"]["artifacts"]
        ],
        "animation_artifacts": [
            {
                "kind": "animation-review-video",
                "relative_path": "review/animation.mp4",
                "size_bytes": video.stat().st_size,
                "sha256": _sha(video.read_bytes()),
            }
        ],
        "animation_complete": True,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": False,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_manifest_and_core_receipt_keep_human_acceptance_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, *_ = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_animation_execution_receipt(manifest, request=request)
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["animation_complete"] is True
    assert receipt["held_out_evaluation_disclosed"] is False
    assert receipt["human_animated_visual_acceptance_required"] is True
    assert receipt["p2_animated_teacher_acceptance_authority"] is False
    assert receipt["quest_distillation_authorized"] is False
    assert receipt["production_activation"] is False


def test_resealed_receipt_cannot_drop_camera_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, *_ = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_animation_execution_receipt(manifest, request=request)
    receipt["consumed_motion_artifacts"] = [
        item
        for item in receipt["consumed_motion_artifacts"]
        if "/cam_params/" not in item["relative_path"]
    ]
    receipt["p2_exavatar_animation_execution_receipt_sha256"] = runner._digest(
        receipt,
        omit="p2_exavatar_animation_execution_receipt_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarAnimationRunnerError,
        match="omits consumed frame/camera/SMPL-X bytes",
    ):
        validate_animation_execution_receipt(receipt)


def test_resealed_receipt_cannot_grant_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, *_ = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_animation_execution_receipt(manifest, request=request)
    receipt["p2_animated_teacher_acceptance_authority"] = True
    receipt["p2_exavatar_animation_execution_receipt_sha256"] = runner._digest(
        receipt,
        omit="p2_exavatar_animation_execution_receipt_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarAnimationRunnerError,
        match="authority mismatch: p2_animated_teacher_acceptance_authority",
    ):
        validate_animation_execution_receipt(receipt)
