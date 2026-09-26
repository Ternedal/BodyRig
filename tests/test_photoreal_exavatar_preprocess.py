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


def test_require_finite_numeric_json_rejects_nan(tmp_path: Path) -> None:
    path = tmp_path / "joint_offset.json"
    path.write_text("[[0.0, NaN, 0.0]]", encoding="utf-8")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="non-finite values.*\$\[0\]\[1\]",
    ):
        preprocess._require_finite_numeric_json(path, label="SMPL-X fit")


def test_require_finite_numeric_json_accepts_nested_numeric_payload(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    path.write_text(
        json.dumps({"pose": [[0.0, 1.0, -2.0]], "trans": [1, 2, 3]}),
        encoding="utf-8",
    )

    record = preprocess._require_finite_numeric_json(path, label="SMPL-X fit")

    assert record["all_numeric_values_finite"] is True
    assert record["numeric_value_count"] == 6
    assert record["sha256"] == preprocess._file_sha(path)


def test_require_finite_smplx_fit_outputs_checks_identity_and_frames(tmp_path: Path) -> None:
    optimized = tmp_path / "smplx_optimized"
    params = optimized / "smplx_params"
    params.mkdir(parents=True)
    for name, payload in (
        ("shape_param.json", [0.0, 1.0]),
        ("face_offset.json", [[0.0, 0.0, 0.0]]),
        ("joint_offset.json", [[0.0, 0.0, 0.0]]),
        ("locator_offset.json", [[0.0, 0.0, 0.0]]),
    ):
        (optimized / name).write_text(json.dumps(payload), encoding="utf-8")
    (params / "0.json").write_text(
        json.dumps({"root_pose": [0.0, 0.0, 0.0], "trans": [0.0, 0.0, 1.0]}),
        encoding="utf-8",
    )

    records = preprocess._require_finite_smplx_fit_outputs(
        optimized,
        [0],
        label="SMPL-X fit",
    )

    assert len(records) == 5
    assert all(record["all_numeric_values_finite"] is True for record in records)


def test_background_point_cloud_validation_accepts_finite_rasterizable_points(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 0.3 0 10 255\n"
        "1 0 0.4 20 30 40\n"
        "0 1 0.5 50 60 70\n"
        "1 1 0.6 80 90 100\n",
        encoding="utf-8",
    )

    stats = preprocess._validate_background_point_cloud(
        path,
        camera_mode="virtual",
    )

    assert stats["camera_mode"] == "virtual"
    assert stats["point_count"] == 4
    assert stats["rasterizable_point_count"] == 4
    assert stats["virtual_near_plane_rule_applied"] is True
    assert stats["min_z"] == pytest.approx(0.3)
    assert stats["max_z"] == pytest.approx(0.6)
    assert stats["sha256"] == preprocess._file_sha(path)


def test_background_point_cloud_validation_rejects_nonfinite_geometry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 0.3 0 10 255\n"
        "1 0 0.4 20 30 40\n"
        "0 1 inf 50 60 70\n"
        "1 1 0.6 80 90 100\n",
        encoding="utf-8",
    )

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="non-finite values",
    ):
        preprocess._validate_background_point_cloud(
            path,
            camera_mode="virtual",
        )


def test_background_point_cloud_colmap_does_not_apply_world_z_near_plane(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 -10 0 10 255\n"
        "1 0 -9 20 30 40\n"
        "0 1 -8 50 60 70\n"
        "1 1 -7 80 90 100\n",
        encoding="utf-8",
    )

    stats = preprocess._validate_background_point_cloud(
        path,
        camera_mode="colmap",
    )

    assert stats["camera_mode"] == "colmap"
    assert stats["point_count"] == 4
    assert stats["rasterizable_point_count"] is None
    assert stats["world_z_gt_0_2_point_count"] == 0
    assert stats["virtual_near_plane_rule_applied"] is False


def test_validate_diagnostic_fit_source_accepts_complete_finite_fit(tmp_path: Path) -> None:
    source = tmp_path / "bodyrig-fit-diagnostic" / "bodyrig-42"
    optimized = source / "smplx_optimized"
    params = optimized / "smplx_params"
    params.mkdir(parents=True)
    for name, payload in (
        ("shape_param.json", [0.0, 1.0]),
        ("face_offset.json", [[0.0, 0.0, 0.0]]),
        ("joint_offset.json", [[0.0, 0.0, 0.0]]),
        ("locator_offset.json", [[0.0, 0.0, 0.0]]),
    ):
        (optimized / name).write_text(json.dumps(payload), encoding="utf-8")
    (params / "0.json").write_text(
        json.dumps({"root_pose": [0.0, 0.0, 0.0], "trans": [0.0, 0.0, 1.0]}),
        encoding="utf-8",
    )
    for name in (
        "smplx_wo_pose_wo_expr.ply",
        "smplx_wo_pose_wo_expr_wo_fo.ply",
        "flame_wo_pose_wo_expr.ply",
    ):
        (optimized / name).write_bytes(b"ply")
    meshes = optimized / "meshes"
    renders = optimized / "renders"
    meshes.mkdir()
    renders.mkdir()
    (meshes / "0_smplx.ply").write_bytes(b"ply")
    (meshes / "0_flame.ply").write_bytes(b"ply")
    (renders / "0_smplx.jpg").write_bytes(b"jpg")
    (source / "smplx_optimized.mp4").write_bytes(b"diagnostic-video")

    records = preprocess._validate_diagnostic_fit_source(source, [0])

    assert len(records) == 5
    assert all(record["all_numeric_values_finite"] is True for record in records)


def test_completed_stage_validation_accepts_strict_finite_metadata(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    value = root / "joint_offset.json"
    value.write_text("[[0.0, 0.0, 0.0]]", encoding="utf-8")
    state = {
        "completed_stages": [
            {
                "name": "smplx-fit",
                "outputs": [
                    {
                        "path": value.resolve().as_posix(),
                        "size_bytes": value.stat().st_size,
                        "sha256": preprocess._file_sha(value),
                        "numeric_value_count": 3,
                        "all_numeric_values_finite": True,
                    }
                ],
            }
        ]
    }

    preprocess._validate_completed_stage_outputs(root, state)


def test_completed_stage_validation_rejects_false_finite_metadata(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    value = root / "joint_offset.json"
    value.write_text("[[0.0, 0.0, 0.0]]", encoding="utf-8")
    state = {
        "completed_stages": [
            {
                "name": "smplx-fit",
                "outputs": [
                    {
                        "path": value.resolve().as_posix(),
                        "size_bytes": value.stat().st_size,
                        "sha256": preprocess._file_sha(value),
                        "numeric_value_count": 3,
                        "all_numeric_values_finite": False,
                    }
                ],
            }
        ]
    }

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="finite metadata is invalid",
    ):
        preprocess._validate_completed_stage_outputs(root, state)


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



def test_trusted_mmpose_checkpoint_env_requires_hash_bound_reference_assets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    records: list[dict[str, object]] = []
    for destination, source_relative in preprocess.MMPOSE_TRUSTED_CHECKPOINTS.items():
        checkpoint = root / destination
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(destination.encode("utf-8"))
        records.append(
            {
                "source_relative_path": source_relative,
                "destination": destination,
                "sha256": preprocess._file_sha(checkpoint),
                "reference_vision_asset": True,
            }
        )

    env = preprocess._trusted_mmpose_checkpoint_env(root, {"linked_assets": records})

    assert env == {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"}


def test_trusted_mmpose_checkpoint_env_accepts_hash_bound_leaf_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    reference_root = tmp_path / "reference-models"
    records: list[dict[str, object]] = []
    try:
        for index, (destination, source_relative) in enumerate(
            preprocess.MMPOSE_TRUSTED_CHECKPOINTS.items()
        ):
            source = reference_root / source_relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"trusted-{index}".encode("utf-8"))
            checkpoint = root / destination
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.symlink_to(source)
            records.append(
                {
                    "source_relative_path": source_relative,
                    "destination": destination,
                    "sha256": preprocess._file_sha(source),
                    "reference_vision_asset": True,
                }
            )
    except (OSError, NotImplementedError):
        pytest.skip("file symlink not available")

    env = preprocess._trusted_mmpose_checkpoint_env(root, {"linked_assets": records})

    assert env == {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"}


def test_trusted_mmpose_checkpoint_env_rejects_parent_symlink_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "repos").parent.mkdir(parents=True, exist_ok=True)
        (root / "repos").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink not available")

    destination = "repos/mmpose/checkpoint.pth"
    source_relative = "weights/checkpoint.pth"
    checkpoint = outside / "mmpose" / "checkpoint.pth"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"trusted")
    monkeypatch.setattr(
        preprocess,
        "MMPOSE_TRUSTED_CHECKPOINTS",
        {destination: source_relative},
    )
    records = [
        {
            "source_relative_path": source_relative,
            "destination": destination,
            "sha256": preprocess._file_sha(checkpoint),
            "reference_vision_asset": True,
        }
    ]

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="checkpoint escapes workspace",
    ):
        preprocess._trusted_mmpose_checkpoint_env(root, {"linked_assets": records})


def test_trusted_mmpose_checkpoint_env_rejects_drifted_checkpoint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    records: list[dict[str, object]] = []
    for destination, source_relative in preprocess.MMPOSE_TRUSTED_CHECKPOINTS.items():
        checkpoint = root / destination
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(destination.encode("utf-8"))
        records.append(
            {
                "source_relative_path": source_relative,
                "destination": destination,
                "sha256": preprocess._file_sha(checkpoint),
                "reference_vision_asset": True,
            }
        )

    first = root / next(iter(preprocess.MMPOSE_TRUSTED_CHECKPOINTS))
    first.write_bytes(b"drifted")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="checkpoint bytes drifted",
    ):
        preprocess._trusted_mmpose_checkpoint_env(root, {"linked_assets": records})


def test_run_stage_applies_scoped_environment_overrides(
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
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(preprocess.subprocess, "run", fake_run)
    monkeypatch.delenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", raising=False)

    preprocess._run_stage(
        [str(python), "run_mmpose.py"],
        cwd=cwd,
        log_path=tmp_path / "logs" / "mmpose.log",
        label="mmpose",
        env_overrides={"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"},
    )

    env = captured["kwargs"]["env"]
    assert env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] == "1"
    assert os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD") is None


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
    (source / "smplx_optimized").mkdir()
    (source / "smplx_optimized" / "shape_param.json").write_text("{}", encoding="utf-8")
    (source / "smplx_optimized.mp4").write_bytes(b"fit-video")
    (dataset / "smplx_optimized").mkdir()
    (dataset / "smplx_optimized" / "preserve.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="collides"):
        preprocess._move_fit_outputs(source, dataset)

    assert (source / "smplx_optimized" / "shape_param.json").is_file()
    assert (source / "smplx_optimized.mp4").read_bytes() == b"fit-video"
    assert not (dataset / "smplx_optimized.mp4").exists()
    assert (dataset / "smplx_optimized" / "preserve.txt").read_text(encoding="utf-8") == "preserve"
    assert not preprocess._fit_publish_journal_path(dataset).exists()


def test_recover_interrupted_fit_publication_removes_only_journal_owned_paths(tmp_path: Path) -> None:
    source = tmp_path / "fit-result"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "smplx_optimized").mkdir()
    (source / "smplx_optimized" / "partial.txt").write_text("partial", encoding="utf-8")
    (dataset / "smplx_optimized.mp4").write_bytes(b"partial-video")
    (dataset / "frames").mkdir()
    (dataset / "frames" / "0.png").write_bytes(b"authorized")
    preprocess._write_fit_publish_journal(dataset, ["smplx_optimized", "smplx_optimized.mp4"])

    recovered = preprocess._recover_interrupted_fit_publication(source, dataset)

    assert recovered is True
    assert not source.exists()
    assert not (dataset / "smplx_optimized").exists()
    assert not (dataset / "smplx_optimized.mp4").exists()
    assert (dataset / "frames" / "0.png").read_bytes() == b"authorized"
    assert not preprocess._fit_publish_journal_path(dataset).exists()


def test_fit_publish_journal_rejects_unsafe_entry(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="unsafe entry"):
        preprocess._write_fit_publish_journal(dataset, ["../outside"])



def test_fit_publish_journal_rejects_unexpected_safe_output_name(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="unexpected output set"):
        preprocess._write_fit_publish_journal(dataset, ["frames", "smplx_optimized"])



def test_fit_publication_journal_survives_move_until_state_commit_boundary(tmp_path: Path) -> None:
    source = tmp_path / "fit-result"
    dataset = tmp_path / "dataset"
    source.mkdir()
    dataset.mkdir()
    (source / "smplx_optimized").mkdir()
    (source / "smplx_optimized" / "shape_param.json").write_text("{}", encoding="utf-8")
    (source / "smplx_optimized.mp4").write_bytes(b"fit-video")

    journal = preprocess._move_fit_outputs(source, dataset)

    assert journal == preprocess._fit_publish_journal_path(dataset)
    assert journal.is_file()
    assert (dataset / "smplx_optimized" / "shape_param.json").is_file()
    assert (dataset / "smplx_optimized.mp4").read_bytes() == b"fit-video"

    assert preprocess._finalize_fit_publish_journal(dataset) is True
    assert not journal.exists()



def test_copy_unwrapped_requires_exact_pinned_output_set(tmp_path: Path) -> None:
    source = tmp_path / "unwrapped"
    target = tmp_path / "optimized"
    source.mkdir()
    (source / "face_texture.png").write_bytes(b"texture")
    (source / "face_texture_mask.png").write_bytes(b"mask")
    (source / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="output set is not pinned upstream output",
    ):
        preprocess._copy_unwrapped(source, target)

    assert (source / "face_texture.png").is_file()
    assert (source / "face_texture_mask.png").is_file()
    assert (source / "unexpected.txt").is_file()
    assert not target.exists()


def test_copy_unwrapped_preflights_collisions_before_moving(tmp_path: Path) -> None:
    source = tmp_path / "unwrapped"
    target = tmp_path / "optimized"
    source.mkdir()
    target.mkdir()
    (source / "face_texture.png").write_bytes(b"texture")
    (source / "face_texture_mask.png").write_bytes(b"mask")
    (target / "face_texture_mask.png").write_bytes(b"preserve")

    with pytest.raises(
        preprocess.PhotorealExAvatarPreprocessError,
        match="destination already exists",
    ):
        preprocess._copy_unwrapped(source, target)

    assert (source / "face_texture.png").read_bytes() == b"texture"
    assert (source / "face_texture_mask.png").read_bytes() == b"mask"
    assert not (target / "face_texture.png").exists()
    assert (target / "face_texture_mask.png").read_bytes() == b"preserve"


def test_copy_unwrapped_moves_exact_pinned_outputs(tmp_path: Path) -> None:
    source = tmp_path / "unwrapped"
    target = tmp_path / "optimized"
    source.mkdir()
    (source / "face_texture.png").write_bytes(b"texture")
    (source / "face_texture_mask.png").write_bytes(b"mask")

    preprocess._copy_unwrapped(source, target)

    assert not (source / "face_texture.png").exists()
    assert not (source / "face_texture_mask.png").exists()
    assert (target / "face_texture.png").read_bytes() == b"texture"
    assert (target / "face_texture_mask.png").read_bytes() == b"mask"
