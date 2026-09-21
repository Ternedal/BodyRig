from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_p2_exavatar_heldout_evaluation_adapter.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_test_p2_exavatar_heldout_evaluation_adapter",
    ADAPTER_PATH,
)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def _request() -> dict[str, object]:
    value = {
        "format": adapter.REQUEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "train_animation_execution_receipt_sha256": "4" * 64,
        "p2_exavatar_heldout_evaluation_input_sha256": "5" * 64,
        "exavatar_workspace_sha256": "6" * 64,
        "exavatar_preprocess_state_sha256": "7" * 64,
        "exavatar_upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "exavatar_upstream_commit": adapter.PINNED_UPSTREAM_COMMIT,
        "exavatar_subject_id": "bodyrig-42",
        "test_epoch": 4,
        "adapter_revision": adapter._file_sha(ADAPTER_PATH),
        "bodyrig_linux_repo_root": "/bodyrig",
        "adapter_linux_path": str(ADAPTER_PATH),
        "teacher_checkpoint": {
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": 10,
            "sha256": "8" * 64,
            "linux_source_path": "/teacher/snapshot_4.pth",
        },
        "identity_artifacts": [
            {
                "kind": kind,
                "export_relative_path": f"identity/{filename}",
                "size_bytes": 10,
                "sha256": sha * 64,
                "linux_source_path": f"/identity/{filename}",
            }
            for kind, filename, sha in (
                ("shape-param", "shape_param.json", "a"),
                ("face-offset", "face_offset.json", "b"),
                ("joint-offset", "joint_offset.json", "c"),
                ("locator-offset", "locator_offset.json", "d"),
            )
        ],
        "held_out_motion": {
            "source_ref": "src-eval",
            "split": "evaluation",
            "role": "held-out-motion-validation",
            "selected_eye": "mono",
            "selected_viewport_id": None,
            "anchor_observation_ref": "obs-eval",
            "anchor_frame_sha256": "e" * 64,
            "window_start_seconds": 10.0,
            "window_end_seconds": 14.0,
            "window_duration_seconds": 4.0,
            "motion_path_relative": "tasks/src-eval/motion",
            "frame_count": 1,
            "frame_ids": [20],
            "artifacts": [
                {
                    "relative_path": relative,
                    "size_bytes": 10,
                    "sha256": sha * 64,
                    "linux_source_path": f"/motion/{Path(relative).name}",
                }
                for relative, sha in (
                    ("tasks/src-eval/motion/frames/20.png", "f"),
                    ("tasks/src-eval/motion/cam_params/20.json", "1"),
                    (
                        "tasks/src-eval/motion/smplx_optimized/smplx_params_smoothed/20.json",
                        "2",
                    ),
                )
            ],
        },
        "evaluation_mode": "inference-only-held-out",
        "held_out_disclosure_purpose": adapter.DISCLOSURE_PURPOSE,
        "teacher_training_authorized": False,
        "checkpoint_mutation_authorized": False,
        "source_media_rehash_performed": False,
        "held_out_evaluation_disclosed": True,
        "human_animated_visual_acceptance_required": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p2_exavatar_heldout_evaluation_request_sha256"] = adapter._digest(
        value,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    )
    return value


def _patch_common_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adapter,
        "_validate_workspace",
        lambda root, request: {
            "workspace_sha256": request["exavatar_workspace_sha256"],
        },
    )
    monkeypatch.setattr(
        adapter,
        "_validate_preprocess",
        lambda root, request: {
            "preprocess_state_sha256": request[
                "exavatar_preprocess_state_sha256"
            ],
        },
    )
    monkeypatch.setattr(
        adapter,
        "_validate_runtime_preflight",
        lambda path, workspace_sha: {"runtime_environment_ready": True},
    )


def test_heldout_adapter_request_is_evaluation_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    _patch_common_authority(monkeypatch)
    adapter._validate_request(
        request,
        workspace_root=tmp_path,
        runtime_preflight_path=tmp_path / "runtime.json",
    )


def test_heldout_adapter_rejects_train_motion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    request["held_out_motion"]["split"] = "train"
    request["held_out_motion"]["role"] = "motion-driver"
    request["p2_exavatar_heldout_evaluation_request_sha256"] = adapter._digest(
        request,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    )
    _patch_common_authority(monkeypatch)
    with pytest.raises(
        adapter.ExAvatarP2HeldoutEvaluationAdapterError,
        match="EVALUATION-motion-only",
    ):
        adapter._validate_request(
            request,
            workspace_root=tmp_path,
            runtime_preflight_path=tmp_path / "runtime.json",
        )


def test_heldout_adapter_rejects_training_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    request["teacher_training_authorized"] = True
    request["p2_exavatar_heldout_evaluation_request_sha256"] = adapter._digest(
        request,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    )
    _patch_common_authority(monkeypatch)
    with pytest.raises(
        adapter.ExAvatarP2HeldoutEvaluationAdapterError,
        match="teacher_training_authorized",
    ):
        adapter._validate_request(
            request,
            workspace_root=tmp_path,
            runtime_preflight_path=tmp_path / "runtime.json",
        )


def test_heldout_adapter_reuses_hardened_staging_with_evaluation_motion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    observed: dict[str, object] = {}

    def fake_prepare(stage: Path, staging_request: dict[str, object], *, workspace_root: Path):
        observed["stage"] = stage
        observed["workspace_root"] = workspace_root
        observed["motion_driver"] = staging_request["motion_driver"]
        return (
            tmp_path / "main",
            tmp_path / "motion",
            [{"kind": "shape-param", "sha256": "a" * 64}],
            [{"relative_path": "tasks/src-eval/motion/frames/20.png", "sha256": "f" * 64}],
        )

    monkeypatch.setattr(adapter, "_prepare_stage", fake_prepare)
    stage = tmp_path / "stage"
    stage.mkdir()
    adapter._prepare_evaluation_stage(
        stage,
        request,
        workspace_root=tmp_path / "workspace",
    )

    assert observed["motion_driver"] == request["held_out_motion"]
    assert observed["motion_driver"]["split"] == "evaluation"
    assert observed["motion_driver"]["role"] == "held-out-motion-validation"


def test_heldout_adapter_rejects_boolean_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request()
    request["version"] = True
    request["p2_exavatar_heldout_evaluation_request_sha256"] = adapter._digest(
        request,
        omit="p2_exavatar_heldout_evaluation_request_sha256",
    )
    _patch_common_authority(monkeypatch)
    with pytest.raises(
        adapter.ExAvatarP2HeldoutEvaluationAdapterError,
        match="format/version mismatch",
    ):
        adapter._validate_request(
            request,
            workspace_root=tmp_path,
            runtime_preflight_path=tmp_path / "runtime.json",
        )
