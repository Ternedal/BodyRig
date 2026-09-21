from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_p2_exavatar_animation_adapter.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_test_p2_exavatar_animation_adapter",
    ADAPTER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    repo = root / "repos" / "ExAvatar_RELEASE"
    for relative, content in (
        ("avatar/main/animate.py", "# fake animate\n"),
        ("avatar/main/model.py", "# fake model\n"),
        ("avatar/main/config.py", "dataset = 'Custom'\n"),
        ("avatar/common/base.py", "# fake base\n"),
        ("avatar/data/Custom/Custom.py", "# fake custom\n"),
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    workspace = {
        "format": adapter.WORKSPACE_FORMAT,
        "version": 1,
        "performer_id": "42",
        "subject_id": "bodyrig-42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "upstream_commit": adapter.PINNED_UPSTREAM_COMMIT,
        "repository_commits": {"ExAvatar_RELEASE": adapter.PINNED_UPSTREAM_COMMIT},
        "dataset": "Custom",
        "smplx_gender": "female",
        "avatar_config_patch": {
            "relative_path": "avatar/main/config.py",
            "before_sha256": "a" * 64,
            "after_sha256": adapter._file_sha(repo / "avatar" / "main" / "config.py"),
            "dataset": "Custom",
            "smplx_gender": "female",
        },
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "dependency_root_modified": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    workspace["workspace_sha256"] = adapter._digest(
        workspace,
        omit="workspace_sha256",
    )
    _write_json(root / "workspace-receipt.json", workspace)

    preprocess = {
        "format": adapter.PREPROCESS_FORMAT,
        "version": 1,
        "workspace_sha256": workspace["workspace_sha256"],
        "preprocessing_complete": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    preprocess["preprocess_state_sha256"] = adapter._digest(
        preprocess,
        omit="preprocess_state_sha256",
    )
    _write_json(root / "preprocess-state.json", preprocess)

    preflight = {
        "format": adapter.RUNTIME_PREFLIGHT_FORMAT,
        "version": 1,
        "workspace_sha256": workspace["workspace_sha256"],
        "runtime_environment_ready": True,
        "blockers": [],
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    preflight["runtime_preflight_sha256"] = adapter._digest(
        preflight,
        omit="runtime_preflight_sha256",
    )
    preflight_path = root / "runtime-preflight.json"
    _write_json(preflight_path, preflight)
    return root, preflight_path


def _source(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "linux_source_path": str(path),
        "size_bytes": len(payload),
        "sha256": adapter._file_sha(path),
    }


def _request(tmp_path: Path, workspace: Path) -> dict[str, object]:
    receipt = json.loads(
        (workspace / "workspace-receipt.json").read_text(encoding="utf-8")
    )
    preprocess = json.loads(
        (workspace / "preprocess-state.json").read_text(encoding="utf-8")
    )
    inputs = tmp_path / "inputs"
    checkpoint = _source(inputs / "checkpoint.pth", b"checkpoint")
    identity = []
    for kind, filename in adapter.IDENTITY_KINDS.items():
        identity.append(
            {
                "kind": kind,
                "export_relative_path": f"identity/{filename}",
                **_source(inputs / filename, f"{kind}\n".encode()),
            }
        )
    ref = "src-train"
    motion = []
    for relative, payload in (
        (f"tasks/{ref}/motion/frames/10.png", b"frame"),
        (f"tasks/{ref}/motion/cam_params/10.json", b"{}\n"),
        (
            f"tasks/{ref}/motion/smplx_optimized/smplx_params_smoothed/10.json",
            b"{}\n",
        ),
    ):
        motion.append(
            {
                "relative_path": relative,
                **_source(inputs / relative, payload),
            }
        )

    request = {
        "format": adapter.REQUEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "exavatar_workspace_sha256": receipt["workspace_sha256"],
        "exavatar_preprocess_state_sha256": preprocess[
            "preprocess_state_sha256"
        ],
        "exavatar_upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "exavatar_upstream_commit": adapter.PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": "bodyrig-42",
        "test_epoch": 4,
        "adapter_revision": adapter._file_sha(ADAPTER_PATH),
        "bodyrig_linux_repo_root": "/bodyrig",
        "adapter_linux_path": "/bodyrig/tools/photoreal_p2_exavatar_animation_adapter.py",
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            **checkpoint,
        },
        "identity_artifacts": identity,
        "motion_driver": {
            "source_ref": ref,
            "split": "train",
            "role": "motion-driver",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": "obs-train",
            "anchor_frame_sha256": "4" * 64,
            "window_start_seconds": 8.0,
            "window_end_seconds": 12.0,
            "window_duration_seconds": 4.0,
            "motion_path_relative": f"tasks/{ref}/motion",
            "frame_count": 1,
            "frame_ids": [10],
            "artifacts": motion,
        },
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": False,
        "train_motion_driver_only": True,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    request["p2_exavatar_animation_request_sha256"] = adapter._digest(
        request,
        omit="p2_exavatar_animation_request_sha256",
    )
    return request


def test_adapter_request_binds_workspace_preprocess_runtime_and_own_bytes(
    tmp_path: Path,
) -> None:
    workspace, preflight = _workspace(tmp_path)
    request = _request(tmp_path, workspace)
    adapter._validate_request(
        request,
        workspace_root=workspace,
        runtime_preflight_path=preflight,
    )


def test_adapter_stage_contains_only_checkpoint_identity_and_train_motion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace, _preflight = _workspace(tmp_path)
    request = _request(tmp_path, workspace)
    monkeypatch.setattr(
        adapter,
        "_git",
        lambda _repo, *args: (
            adapter.PINNED_UPSTREAM_COMMIT
            if args[:2] == ("rev-parse", "HEAD")
            else ""
        ),
    )
    stage = tmp_path / "stage"
    stage.mkdir()
    main, motion, consumed_identity, consumed_motion = adapter._prepare_stage(
        stage,
        request,
        workspace_root=workspace,
    )

    subject = request["exavatar_subject_id"]
    assert (main / "animate.py").is_file()
    assert (
        stage
        / "avatar"
        / "output"
        / "model_dump"
        / str(subject)
        / "snapshot_4.pth"
    ).is_file()
    identity_root = (
        stage
        / "avatar"
        / "data"
        / "Custom"
        / "data"
        / str(subject)
        / "smplx_optimized"
    )
    assert {path.name for path in identity_root.iterdir()} == set(
        adapter.IDENTITY_KINDS.values()
    )
    assert (motion / "frames" / "10.png").is_file()
    assert (motion / "cam_params" / "10.json").is_file()
    assert (
        motion
        / "smplx_optimized"
        / "smplx_params_smoothed"
        / "10.json"
    ).is_file()
    assert {item["kind"] for item in consumed_identity} == set(
        adapter.IDENTITY_KINDS
    )
    assert len(consumed_motion) == 3
    assert not any("eval" in path.as_posix().lower() for path in stage.rglob("*"))


def test_adapter_rejects_heldout_motion_request(tmp_path: Path) -> None:
    workspace, preflight = _workspace(tmp_path)
    request = _request(tmp_path, workspace)
    request["motion_driver"]["split"] = "evaluation"
    request["motion_driver"]["role"] = "held-out-motion-validation"
    request["p2_exavatar_animation_request_sha256"] = adapter._digest(
        request,
        omit="p2_exavatar_animation_request_sha256",
    )
    with pytest.raises(
        adapter.ExAvatarP2AnimationAdapterError,
        match="TRAIN-motion-only",
    ):
        adapter._validate_request(
            request,
            workspace_root=workspace,
            runtime_preflight_path=preflight,
        )


def test_adapter_rejects_resealed_workspace_drift(tmp_path: Path) -> None:
    workspace, preflight = _workspace(tmp_path)
    request = _request(tmp_path, workspace)
    receipt_path = workspace / "workspace-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["held_out_evaluation_disclosed"] = True
    receipt["workspace_sha256"] = adapter._digest(
        receipt,
        omit="workspace_sha256",
    )
    _write_json(receipt_path, receipt)
    with pytest.raises(
        adapter.ExAvatarP2AnimationAdapterError,
        match="differs from accepted animation input|authority mismatch",
    ):
        adapter._validate_request(
            request,
            workspace_root=workspace,
            runtime_preflight_path=preflight,
        )
