from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preprocess as preprocess
from bodyrig.photoreal_exavatar_preprocess_cli import _guard_plan


def _workspace(tmp_path: Path, *, frame_count: int = 9, gender: str = "female") -> Path:
    root = tmp_path / "workspace"
    dataset = root / "dataset" / "bodyrig-42"
    dataset.mkdir(parents=True)
    (dataset / "frame_list_train.txt").write_text("".join(f"{i}\n" for i in range(frame_count)), encoding="utf-8")
    receipt: dict[str, object] = {
        "format": preprocess.WORKSPACE_FORMAT,
        "version": 1,
        "performer_id": "42",
        "subject_id": "bodyrig-42",
        "selected_epoch_id": "epoch-a",
        "benchmark_plan_sha256": "a" * 64,
        "teacher_input_sha256": "b" * 64,
        "materialization_receipt_sha256": "c" * 64,
        "strict_preflight_sha256": "d" * 64,
        "upstream_commit": "e" * 40,
        "repository_commits": {f"repo-{i}": "f" * 40 for i in range(7)},
        "smplx_gender": gender,
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "dataset": "Custom",
        "fitting_config_sha256": "1" * 64,
        "avatar_config_patch": {},
        "injected_patch_files": [],
        "linked_assets": [],
        "frame_count": frame_count,
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
    receipt["workspace_sha256"] = preprocess._digest(receipt, omit="workspace_sha256")
    (root / "workspace-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


def test_virtual_preprocess_plan_is_explicit_and_adds_depth_stage(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )

    assert plan["smplx_gender"] == "female"
    assert plan["camera_mode"] == "virtual"
    assert [stage["name"] for stage in plan["stages"]] == [
        "camera",
        "deca-flame",
        "hand4whole-smplx-init",
        "wholebody-keypoints",
        "smplx-fit",
        "face-texture-unwrap",
        "smplx-smooth",
        "sam-masks",
        "background-depth",
    ]
    assert plan["held_out_evaluation_disclosed"] is False
    assert plan["photoreal_acceptance_authority"] is False
    assert plan["production_activation"] is False


def test_colmap_plan_uses_colmap_background_without_depth_stage(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="colmap",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert names[-1] == "background-colmap"
    assert "background-depth" not in names


def test_preprocess_plan_requires_explicit_camera_mode(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="explicitly colmap or virtual"):
        preprocess.build_preprocess_plan(
            workspace_root=root,
            camera_mode="auto",
            python_executable="/opt/bodyrig-exavatar/bin/python",
        )


def test_operator_guard_refuses_to_change_upstream_smoothing_semantics(tmp_path: Path) -> None:
    root = _workspace(tmp_path, frame_count=8)
    python = tmp_path / "python"
    python.write_bytes(b"stub")
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable=str(python),
    )

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="fewer than 9 authorized frames"):
        _guard_plan(plan, str(python))


def test_operator_guard_accepts_upstream_smoothing_window_when_python_exists(tmp_path: Path) -> None:
    root = _workspace(tmp_path, frame_count=9)
    python = tmp_path / "python"
    python.write_bytes(b"stub")
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable=str(python),
    )
    _guard_plan(plan, str(python))


def test_clear_uncommitted_fit_output_removes_only_regular_directory(tmp_path: Path) -> None:
    path = tmp_path / "partial-fit"
    path.mkdir()
    (path / "partial.json").write_text("{}", encoding="utf-8")

    preprocess._clear_uncommitted_directory(path, label="SMPL-X fit output")

    assert not path.exists()


def test_clear_uncommitted_fit_output_refuses_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "partial-fit"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink not available")

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="may not be a symlink"):
        preprocess._clear_uncommitted_directory(link, label="SMPL-X fit output")

    assert target.is_dir()


def test_clear_uncommitted_fit_output_refuses_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "partial-fit"
    path.write_text("do not delete", encoding="utf-8")

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="not a directory"):
        preprocess._clear_uncommitted_directory(path, label="SMPL-X fit output")

    assert path.read_text(encoding="utf-8") == "do not delete"


def test_clear_uncommitted_file_removes_only_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "face_texture.png"
    path.write_bytes(b"partial")

    preprocess._clear_uncommitted_file(path, label="face texture output")

    assert not path.exists()


def test_clear_uncommitted_file_refuses_directory(tmp_path: Path) -> None:
    path = tmp_path / "face_texture.png"
    path.mkdir()

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="not a regular file"):
        preprocess._clear_uncommitted_file(path, label="face texture output")

    assert path.is_dir()


def _write_resume_state(
    root: Path,
    plan: dict[str, object],
    output: Path,
) -> dict[str, object]:
    state: dict[str, object] = {
        "format": preprocess.STATE_FORMAT,
        "version": preprocess.VERSION,
        "preprocess_plan_sha256": plan["preprocess_plan_sha256"],
        "workspace_sha256": plan["workspace_sha256"],
        "completed_stages": [
            {
                "name": "camera",
                "outputs": [
                    {
                        "path": output.resolve().as_posix(),
                        "size_bytes": output.stat().st_size,
                        "sha256": preprocess._file_sha(output),
                    }
                ],
            }
        ],
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    (root / "preprocess-state.json").write_text(json.dumps(state), encoding="utf-8")
    return state


def test_load_state_revalidates_completed_output_bytes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )
    output = root / "dataset" / "bodyrig-42" / "cam_params" / "0.json"
    output.parent.mkdir(parents=True)
    output.write_text('{"ok":true}', encoding="utf-8")
    _write_resume_state(root, plan, output)

    loaded = preprocess._load_state(root, plan)

    assert loaded["completed_stages"][0]["name"] == "camera"


def test_load_state_rejects_completed_output_byte_drift(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )
    output = root / "dataset" / "bodyrig-42" / "cam_params" / "0.json"
    output.parent.mkdir(parents=True)
    output.write_text('{"ok":true}', encoding="utf-8")
    _write_resume_state(root, plan, output)
    output.write_text('{"ok":false}', encoding="utf-8")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="output size/path drifted|output SHA-256 drifted",
    ):
        preprocess._load_state(root, plan)


def test_load_state_rejects_final_state_digest_drift(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )
    output = root / "dataset" / "bodyrig-42" / "cam_params" / "0.json"
    output.parent.mkdir(parents=True)
    output.write_text('{"ok":true}', encoding="utf-8")
    state = _write_resume_state(root, plan, output)
    state["preprocessing_complete"] = True
    state["teacher_training_authorized_by_preprocessing"] = False
    state["human_visual_acceptance_required"] = True
    state["preprocess_state_sha256"] = preprocess._digest(
        state,
        omit="preprocess_state_sha256",
    )
    state["human_visual_acceptance_required"] = False
    (root / "preprocess-state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="preprocess state digest mismatch",
    ):
        preprocess._load_state(root, plan)


def test_run_stage_pins_single_gpu_and_egl_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        captured["cwd"] = kwargs["cwd"]
        return Completed()

    monkeypatch.setattr(preprocess.subprocess, "run", fake_run)

    cwd = tmp_path / "stage"
    cwd.mkdir()
    preprocess._run_stage(
        ["/opt/bodyrig-exavatar/bin/python", "fit.py"],
        cwd=cwd,
        log_path=tmp_path / "logs" / "fit.log",
        label="ExAvatar SMPL-X fit stage",
    )

    env = captured["env"]
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["PYOPENGL_PLATFORM"] == "egl"
    assert captured["cwd"] == str(cwd)
