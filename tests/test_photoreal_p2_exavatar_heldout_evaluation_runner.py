from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_exavatar_heldout_evaluation_runner as runner
from bodyrig.photoreal_p2_exavatar_heldout_evaluation_runner import (
    PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
    _validate_manifest,
    build_heldout_evaluation_receipt,
    build_heldout_evaluation_request,
    validate_heldout_evaluation_receipt,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"size_bytes": len(payload), "sha256": _sha(payload)}


def _authority(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path, Path]:
    identity_root = tmp_path / "identity"
    motion_root = tmp_path / "motion"
    teacher_root = tmp_path / "teacher"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    checkpoint = _write(
        teacher_root / "checkpoint" / "snapshot_4.pth",
        b"checkpoint",
    )
    identities = []
    for kind, filename, payload in (
        ("shape-param", "shape_param.json", b"[1]\n"),
        ("face-offset", "face_offset.json", b"[[0,0,0]]\n"),
        ("joint-offset", "joint_offset.json", b"[[0,0,0]]\n"),
        ("locator-offset", "locator_offset.json", b"[[0,0,0]]\n"),
    ):
        record = _write(identity_root / "identity" / filename, payload)
        identities.append(
            {
                "kind": kind,
                "source_relative_path": f"smplx_optimized/{filename}",
                "export_relative_path": f"identity/{filename}",
                **record,
            }
        )

    ref = "src-eval"
    prefix = f"tasks/{ref}/motion"
    motion = []
    for relative, payload in (
        (f"{prefix}/frames/20.png", b"frame"),
        (f"{prefix}/cam_params/20.json", b"{}\n"),
        (
            f"{prefix}/smplx_optimized/smplx_params_smoothed/20.json",
            b"{}\n",
        ),
    ):
        motion.append(
            {"relative_path": relative, **_write(motion_root / relative, payload)}
        )

    authority = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "train_animation_execution_receipt_sha256": "4" * 64,
        "p2_exavatar_heldout_evaluation_input_sha256": "5" * 64,
        "exavatar_workspace_sha256": "6" * 64,
        "exavatar_preprocess_state_sha256": "7" * 64,
        "exavatar_subject_id": "bodyrig-42",
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            **checkpoint,
        },
        "identity_artifacts": identities,
        "held_out_motion": {
            "source_ref": ref,
            "split": "evaluation",
            "role": "held-out-motion-validation",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": "obs-eval",
            "anchor_frame_sha256": "8" * 64,
            "window_start_seconds": 10.0,
            "window_end_seconds": 14.0,
            "window_duration_seconds": 4.0,
            "motion_path_relative": prefix,
            "frame_count": 1,
            "frame_ids": [20],
            "artifacts": motion,
        },
    }
    return authority, identity_root, motion_root, teacher_root, repo_root


def _teacher_config() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-teacher-config",
        "version": 1,
        "adapter": "exavatar-benchmark",
        "revision": "transport-rev",
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
) -> tuple[dict[str, object], dict[str, str | int], Path]:
    authority, identity_root, motion_root, teacher_root, repo_root = _authority(
        tmp_path
    )
    adapter = tmp_path / "heldout-adapter.py"
    adapter.write_text("# heldout adapter\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_heldout_evaluation_input",
        lambda value: authority,
    )
    monkeypatch.setattr(
        runner,
        "make_wsl_path_converter",
        lambda *_args: lambda value: "/linux/" + Path(value).name,
    )
    request, runtime = build_heldout_evaluation_request(
        authority,
        _teacher_config(),
        identity_root=identity_root,
        motion_output_root=motion_root,
        teacher_output_root=teacher_root,
        bodyrig_repo_root=repo_root,
        adapter_script=adapter,
    )
    return request, runtime, adapter


def test_heldout_request_is_evaluation_only_and_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, runtime, adapter = _request(monkeypatch, tmp_path)

    assert request["held_out_motion"]["source_ref"] == "src-eval"
    assert request["held_out_motion"]["split"] == "evaluation"
    assert request["held_out_motion"]["role"] == "held-out-motion-validation"
    assert request["held_out_motion"]["frame_ids"] == [20]
    assert len(request["held_out_motion"]["artifacts"]) == 3
    assert request["evaluation_mode"] == "inference-only-held-out"
    assert request["held_out_evaluation_disclosed"] is True
    assert request["held_out_disclosure_purpose"] == runner.DISCLOSURE_PURPOSE
    assert request["teacher_training_authorized"] is False
    assert request["checkpoint_mutation_authorized"] is False
    assert request["p2_animated_teacher_acceptance_authority"] is False
    assert request["production_activation"] is False
    assert request["adapter_revision"] == _sha(adapter.read_bytes())
    assert runtime["linux_python"] == "/opt/bodyrig-exavatar/bin/python"


def test_heldout_request_rejects_motion_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority, identity_root, motion_root, teacher_root, repo_root = _authority(
        tmp_path
    )
    adapter = tmp_path / "heldout-adapter.py"
    adapter.write_text("# heldout adapter\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_heldout_evaluation_input",
        lambda value: authority,
    )
    monkeypatch.setattr(
        runner,
        "make_wsl_path_converter",
        lambda *_args: lambda value: "/linux/" + Path(value).name,
    )
    (
        motion_root
        / "tasks"
        / "src-eval"
        / "motion"
        / "frames"
        / "20.png"
    ).write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
        match="size/path drifted|bytes drifted",
    ):
        build_heldout_evaluation_request(
            authority,
            _teacher_config(),
            identity_root=identity_root,
            motion_output_root=motion_root,
            teacher_output_root=teacher_root,
            bodyrig_repo_root=repo_root,
            adapter_script=adapter,
        )


def _manifest(
    request: dict[str, object],
    output_root: Path,
) -> dict[str, object]:
    (output_root / "heldout-evaluation-manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    video = output_root / "review" / "heldout-animation.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"heldout-review")
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
        "train_animation_execution_receipt_sha256": request[
            "train_animation_execution_receipt_sha256"
        ],
        "p2_exavatar_heldout_evaluation_input_sha256": request[
            "p2_exavatar_heldout_evaluation_input_sha256"
        ],
        "p2_exavatar_heldout_evaluation_request_sha256": request[
            "p2_exavatar_heldout_evaluation_request_sha256"
        ],
        "exavatar_upstream_commit": runner.PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": request["exavatar_subject_id"],
        "test_epoch": 4,
        "adapter_revision": request["adapter_revision"],
        "held_out_source_ref": request["held_out_motion"]["source_ref"],
        "held_out_frame_count": 1,
        "held_out_frame_ids": [20],
        "consumed_checkpoint_sha256": request["teacher_checkpoint"]["sha256"],
        "consumed_identity_artifacts": [
            {"kind": item["kind"], "sha256": item["sha256"]}
            for item in request["identity_artifacts"]
        ],
        "consumed_held_out_motion_artifacts": [
            {"relative_path": item["relative_path"], "sha256": item["sha256"]}
            for item in request["held_out_motion"]["artifacts"]
        ],
        "evaluation_artifacts": [
            {
                "kind": "heldout-animation-review-video",
                "relative_path": "review/heldout-animation.mp4",
                "size_bytes": video.stat().st_size,
                "sha256": _sha(video.read_bytes()),
            }
        ],
        "evaluation_complete": True,
        "inference_only": True,
        "teacher_training_performed": False,
        "checkpoint_mutation_performed": False,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": True,
        "held_out_disclosure_purpose": runner.DISCLOSURE_PURPOSE,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_heldout_manifest_and_receipt_keep_acceptance_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, _adapter = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_heldout_evaluation_receipt(manifest, request=request)

    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["evaluation_complete"] is True
    assert receipt["inference_only"] is True
    assert receipt["teacher_training_performed"] is False
    assert receipt["checkpoint_mutation_performed"] is False
    assert receipt["held_out_evaluation_disclosed"] is True
    assert receipt["p2_animated_teacher_acceptance_authority"] is False
    assert receipt["quest_distillation_authorized"] is False
    assert receipt["production_activation"] is False


def test_resealed_heldout_receipt_cannot_drop_camera_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, _adapter = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_heldout_evaluation_receipt(manifest, request=request)
    receipt["consumed_held_out_motion_artifacts"] = [
        item
        for item in receipt["consumed_held_out_motion_artifacts"]
        if "/cam_params/" not in item["relative_path"]
    ]
    receipt[
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256"
    ] = runner._digest(
        receipt,
        omit="p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
        match="omits frame/camera/SMPL-X bytes",
    ):
        validate_heldout_evaluation_receipt(receipt)


def test_resealed_heldout_receipt_cannot_enable_training(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, _adapter = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_heldout_evaluation_receipt(manifest, request=request)
    receipt["teacher_training_performed"] = True
    receipt[
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256"
    ] = runner._digest(
        receipt,
        omit="p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
        match="authority mismatch: teacher_training_performed",
    ):
        validate_heldout_evaluation_receipt(receipt)


def test_heldout_receipt_rejects_boolean_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _runtime, _adapter = _request(monkeypatch, tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = _validate_manifest(
        _manifest(request, output),
        request=request,
        output_root=output,
    )
    receipt = build_heldout_evaluation_receipt(manifest, request=request)
    receipt["version"] = True
    receipt[
        "p2_exavatar_heldout_evaluation_execution_receipt_sha256"
    ] = runner._digest(
        receipt,
        omit="p2_exavatar_heldout_evaluation_execution_receipt_sha256",
    )
    with pytest.raises(
        PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
        match="format/version mismatch",
    ):
        validate_heldout_evaluation_receipt(receipt)
