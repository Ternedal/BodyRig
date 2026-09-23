from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

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
        "wholebody-keypoints",
        "deca-flame",
        "hand4whole-smplx-init",
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


def test_preprocess_orders_pinned_keypoints_before_hand4whole(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = preprocess.build_preprocess_plan(
        workspace_root=root,
        camera_mode="virtual",
        python_executable="/opt/bodyrig-exavatar/bin/python",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert names.index("wholebody-keypoints") < names.index("deca-flame")
    assert names.index("wholebody-keypoints") < names.index("hand4whole-smplx-init")



def test_stage_env_prepends_pinned_venv_for_upstream_child_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv = tmp_path / "bodyrig-exavatar"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_bytes(b"stub")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)

    env = preprocess._stage_env(str(python))

    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["PYOPENGL_PLATFORM"] == "egl"


def test_run_stage_passes_pinned_venv_env_to_upstream_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv = tmp_path / "bodyrig-exavatar"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_bytes(b"stub")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    cwd = tmp_path / "stage"
    cwd.mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(preprocess.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/usr/bin")

    preprocess._run_stage(
        [str(python), "run_deca.py", "--root_path", "/dataset"],
        cwd=cwd,
        log_path=tmp_path / "logs" / "deca.log",
        label="DECA",
    )

    env = captured["kwargs"]["env"]
    assert captured["argv"][0] == str(python)
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["PYTHONNOUSERSITE"] == "1"
    assert captured["kwargs"]["shell"] is False



def test_clear_uncommitted_stage_outputs_removes_only_declared_artifacts(tmp_path: Path) -> None:
    partial_dir = tmp_path / "masks"
    partial_dir.mkdir()
    (partial_dir / "0.png").write_bytes(b"partial")
    partial_file = tmp_path / "masks.mp4"
    partial_file.write_bytes(b"partial-video")
    preserved = tmp_path / "frames"
    preserved.mkdir()
    (preserved / "0.png").write_bytes(b"authorized-frame")

    preprocess._clear_uncommitted_stage_outputs(
        directories=(partial_dir,),
        files=(partial_file,),
        label="SAM masks",
    )

    assert not partial_dir.exists()
    assert not partial_file.exists()
    assert (preserved / "0.png").read_bytes() == b"authorized-frame"



def test_move_fit_outputs_preflights_all_collisions_before_mutation(tmp_path: Path) -> None:
    source = tmp_path / "fit-result"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "alpha.txt").write_text("alpha", encoding="utf-8")
    (source / "smplx_optimized").mkdir()
    (source / "smplx_optimized" / "shape_param.json").write_text("{}", encoding="utf-8")
    (dataset / "smplx_optimized").mkdir()
    (dataset / "smplx_optimized" / "preserve.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="collides"):
        preprocess._move_fit_outputs(source, dataset)

    assert (source / "alpha.txt").read_text(encoding="utf-8") == "alpha"
    assert (source / "smplx_optimized" / "shape_param.json").is_file()
    assert not (dataset / "alpha.txt").exists()
    assert (dataset / "smplx_optimized" / "preserve.txt").read_text(encoding="utf-8") == "preserve"
    assert not preprocess._fit_publish_journal_path(dataset).exists()


def test_recover_interrupted_fit_publication_removes_only_journal_owned_paths(tmp_path: Path) -> None:
    source = tmp_path / "fit-result"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "remaining").mkdir()
    (source / "remaining" / "partial.txt").write_text("partial", encoding="utf-8")
    (dataset / "moved").mkdir()
    (dataset / "moved" / "fit.txt").write_text("fit", encoding="utf-8")
    (dataset / "frames").mkdir()
    (dataset / "frames" / "0.png").write_bytes(b"authorized")
    preprocess._write_fit_publish_journal(dataset, ["moved", "remaining"])

    recovered = preprocess._recover_interrupted_fit_publication(source, dataset)

    assert recovered is True
    assert not source.exists()
    assert not (dataset / "moved").exists()
    assert not (dataset / "remaining").exists()
    assert (dataset / "frames" / "0.png").read_bytes() == b"authorized"
    assert not preprocess._fit_publish_journal_path(dataset).exists()


def test_fit_publish_journal_rejects_unsafe_entry(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="unsafe entry"):
        preprocess._write_fit_publish_journal(dataset, ["../outside"])
