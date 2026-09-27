from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_exavatar_teacher_resume_adapter",
        ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_avatar_custom_bbox_patch_adds_temporal_fallback(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "Custom.py"
    path.write_text(
        adapter.AVATAR_CUSTOM_INIT_ORIGINAL
        + "\n"
        + adapter.AVATAR_CUSTOM_LEN_ORIGINAL
        + "\n"
        + adapter.AVATAR_CUSTOM_ITEM_ORIGINAL,
        encoding="utf-8",
    )

    result = adapter._ensure_avatar_custom_bbox_patch(path)
    patched = path.read_text(encoding="utf-8")

    assert result["applied"] is True
    assert "get_bodyrig_body_bbox_init" in patched
    assert "for threshold in (0.5, 0.2)" in patched
    assert "avatar bbox fallback" in patched
    assert "self.bodyrig_body_bboxes[frame_idx].copy()" in patched

    second = adapter._ensure_avatar_custom_bbox_patch(path)
    assert second["applied"] is False


def test_avatar_custom_scene_sampling_patch_is_deterministic(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "Custom.py"
    path.write_text(
        "prefix\n" + adapter.AVATAR_CUSTOM_SCENE_SAMPLE_ORIGINAL + "suffix\n",
        encoding="utf-8",
    )

    first = adapter._ensure_avatar_custom_scene_sampling_patch(path)
    patched = path.read_text(encoding="utf-8")

    assert first["applied"] is True
    assert "torch.Generator(device='cpu')" in patched
    assert "manual_seed(0)" in patched
    assert "bodyrig_scene_keep" in patched
    assert "fewer than four points" in patched

    second = adapter._ensure_avatar_custom_scene_sampling_patch(path)
    assert second["applied"] is False


def test_virtual_background_point_cloud_validation_rejects_nonfinite(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 1 1 2 3\n"
        "0 0 1 1 2 3\n"
        "0 0 1 1 2 3\n"
        "0 0 nan 1 2 3\n",
        encoding="utf-8",
    )

    with pytest.raises(
        adapter.ExAvatarTeacherAdapterError,
        match="non-finite values",
    ):
        adapter._validate_background_point_cloud(
            tmp_path,
            camera_mode="virtual",
        )


def test_virtual_background_point_cloud_validation_reports_scene_stats(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 0.5 10 20 30\n"
        "1 0 0.6 40 50 60\n"
        "0 1 0.7 70 80 90\n"
        "1 1 0.8 100 110 120\n",
        encoding="utf-8",
    )

    stats = adapter._validate_background_point_cloud(
        tmp_path,
        camera_mode="virtual",
    )

    assert stats is not None
    assert stats["camera_mode"] == "virtual"
    assert stats["point_count"] == 4
    assert stats["rasterizable_point_count"] == 4
    assert stats["virtual_near_plane_rule_applied"] is True
    assert stats["min_z"] == pytest.approx(0.5)
    assert stats["max_z"] == pytest.approx(0.8)
    assert stats["sha256"] == adapter._file_sha(path)


def test_background_point_cloud_colmap_skips_world_z_near_plane_rule(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    path = tmp_path / "bkg_point_cloud.txt"
    path.write_text(
        "0 0 -10 10 20 30\n"
        "1 0 -9 40 50 60\n"
        "0 1 -8 70 80 90\n"
        "1 1 -7 100 110 120\n",
        encoding="utf-8",
    )

    stats = adapter._validate_background_point_cloud(
        tmp_path,
        camera_mode="colmap",
    )

    assert stats is not None
    assert stats["camera_mode"] == "colmap"
    assert stats["rasterizable_point_count"] is None
    assert stats["world_z_gt_0_2_point_count"] == 0
    assert stats["virtual_near_plane_rule_applied"] is False


def test_training_finite_guard_covers_loss_gradient_and_parameter(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text(
        adapter.TRAIN_FINITE_ORIGINAL
        + "\n"
        + adapter.TRAIN_STEP_ORIGINAL,
        encoding="utf-8",
    )

    result = adapter._ensure_training_finite_guard(path)
    patched = path.read_text(encoding="utf-8")

    assert result["applied"] is True
    assert "BodyRig non-finite loss before backward" in patched
    assert "BodyRig non-finite gradient after backward" in patched
    assert "scene-scale-probe" in patched
    assert "for source_name in ('rgb_scene', 'ssim_scene')" in patched
    assert "'{}_bad_rows={}/{} first_rows={}'.format(" in patched
    assert "total_scale_bad_rows" in patched
    assert "mean_3d=" in patched
    assert "visible=" in patched
    assert "radius=" in patched
    assert "physical_scale_min=" in patched
    assert "physical_scale_max=" in patched
    assert "torch.autograd.grad" in patched
    assert "BodyRig non-finite parameter after optimizer step" in patched
    assert "torch.isfinite" in patched

    second = adapter._ensure_training_finite_guard(path)
    assert second["applied"] is False


def test_teacher_adapter_emits_pretrain_scene_provenance() -> None:
    adapter = _load_adapter()
    source = ADAPTER_PATH.read_text(encoding="utf-8")

    assert "bodyrig-exavatar-pretrain-diagnostic" in source
    assert '"background_point_cloud": background_point_cloud' in source
    assert '"training_seed": training_seed_patch["seed"]' in source
    assert '"avatar_scene_sampling_patch_sha256"' in source
    assert '"finite_guard_patch_sha256"' in source


def test_training_seed_patch_sets_all_rng_sources(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text(
        adapter.TRAIN_SEED_IMPORT_ORIGINAL
        + "\n"
        + adapter.TRAIN_SEED_MAIN_ORIGINAL,
        encoding="utf-8",
    )

    first = adapter._ensure_training_seed_patch(path)
    patched = path.read_text(encoding="utf-8")

    assert first["applied"] is True
    assert first["seed"] == 0
    assert "import random" in patched
    assert "import numpy as np" in patched
    assert "random.seed(bodyrig_seed)" in patched
    assert "np.random.seed(bodyrig_seed)" in patched
    assert "torch.manual_seed(bodyrig_seed)" in patched
    assert "torch.cuda.manual_seed_all(bodyrig_seed)" in patched

    second = adapter._ensure_training_seed_patch(path)
    assert second["applied"] is False
    assert second["seed"] == 0


def test_arm_rgb_reg_patch_guards_empty_correspondence_support(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "loss.py"
    path.write_text(
        "prefix\n" + adapter.ARM_RGB_REG_ORIGINAL + "suffix\n",
        encoding="utf-8",
    )

    first = adapter._ensure_arm_rgb_reg_empty_support_patch(path)
    patched = path.read_text(encoding="utf-8")

    assert first["applied"] is True
    assert adapter.ARM_RGB_REG_ORIGINAL not in patched
    assert adapter.ARM_RGB_REG_PATCHED in patched
    assert "return rgb.sum() * 0.0" in patched
    assert first["after_sha256"] == adapter._file_sha(path)

    second = adapter._ensure_arm_rgb_reg_empty_support_patch(path)
    assert second["applied"] is False
    assert second["after_sha256"] == first["after_sha256"]


def test_arm_rgb_reg_patch_fails_closed_on_upstream_drift(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "loss.py"
    path.write_text("class ArmRGBReg: pass\n", encoding="utf-8")

    with pytest.raises(
        adapter.ExAvatarTeacherAdapterError,
        match="marker changed or is ambiguous",
    ):
        adapter._ensure_arm_rgb_reg_empty_support_patch(path)


def test_teacher_run_prepends_pinned_pythonpath_and_preserves_inherited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    gaussian_repo = tmp_path / "diff-gaussian-rasterization-depth"
    gaussian_repo.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    log_path = tmp_path / "logs" / "train.log"
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = dict(kwargs["env"])
        captured["cwd"] = kwargs["cwd"]
        return Completed()

    monkeypatch.setenv("PYTHONPATH", "/existing/pythonpath")
    monkeypatch.setattr(adapter.subprocess, "run", fake_run)

    adapter._run(
        [sys.executable, "train.py"],
        cwd=cwd,
        log_path=log_path,
        label="test training",
        pythonpath_roots=(gaussian_repo,),
    )

    env = captured["env"]
    assert env["PYTHONPATH"].split(adapter.os.pathsep) == [
        str(gaussian_repo.resolve()),
        "/existing/pythonpath",
    ]
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["PYOPENGL_PLATFORM"] == "egl"
    assert captured["cwd"] == str(cwd)


def test_teacher_run_rejects_symlink_pythonpath_root(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable in this test environment")

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="missing or unsafe"):
        adapter._run(
            [sys.executable, "train.py"],
            cwd=tmp_path,
            log_path=tmp_path / "train.log",
            label="test training",
            pythonpath_roots=(link,),
        )


def test_snapshot_epochs_accepts_only_exact_nonempty_pinned_epochs(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_0.pth").write_bytes(b"epoch-0")
    (model_dir / "snapshot_2.pth").write_bytes(b"epoch-2")

    assert adapter._snapshot_epochs(model_dir) == [0, 2]


def test_snapshot_epochs_returns_empty_for_missing_model_dir(tmp_path: Path) -> None:
    adapter = _load_adapter()

    assert adapter._snapshot_epochs(tmp_path / "missing") == []


@pytest.mark.parametrize(
    ("name", "payload", "match"),
    [
        ("notes.txt", b"x", "unexpected file"),
        ("snapshot_x.pth", b"x", "invalid ExAvatar snapshot name"),
        ("snapshot_5.pth", b"x", "unexpected ExAvatar snapshot epoch"),
        ("snapshot_1.pth", b"", "empty ExAvatar snapshot"),
    ],
)
def test_snapshot_epochs_fails_closed_on_ambiguous_model_state(
    tmp_path: Path,
    name: str,
    payload: bytes,
    match: str,
) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / name).write_bytes(payload)

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match=match):
        adapter._snapshot_epochs(model_dir)


def test_training_resume_plan_starts_fresh_without_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "fresh"
    assert argv == [sys.executable, "train.py", "--subject_id", "subject-42"]
    assert log_name == "train.log"


def test_training_resume_plan_uses_upstream_continue_from_partial_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_2.pth").write_bytes(b"checkpoint")
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "resume-from-checkpoint"
    assert argv == [
        sys.executable,
        "train.py",
        "--subject_id",
        "subject-42",
        "--continue",
    ]
    assert log_name == "train-resume.log"


def test_training_resume_plan_skips_retraining_when_final_checkpoint_exists(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / f"snapshot_{adapter.FINAL_EPOCH}.pth").write_bytes(b"final-checkpoint")
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "reuse-final-checkpoint"
    assert argv is None
    assert log_name is None


def test_training_resume_plan_rejects_neutral_output_before_final_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_1.pth").write_bytes(b"checkpoint")
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="before final checkpoint"):
        adapter._training_resume_plan(
            model_dir,
            neutral_dir,
            subject="subject-42",
        )


def test_training_resume_plan_rejects_neutral_output_without_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="without any training checkpoint"):
        adapter._training_resume_plan(
            model_dir,
            neutral_dir,
            subject="subject-42",
        )


def test_training_resume_plan_removes_interrupted_atomic_checkpoint_temp(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_1.pth").write_bytes(b"checkpoint")
    temp = model_dir / "snapshot_2.pth.bodyrig-tmp"
    temp.write_bytes(b"partial")
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert temp.exists() is False
    assert mode == "resume-from-checkpoint"
    assert argv == [
        sys.executable,
        "train.py",
        "--subject_id",
        "subject-42",
        "--continue",
    ]
    assert log_name == "train-resume.log"


@pytest.mark.parametrize(
    "name",
    [
        "snapshot_x.pth.bodyrig-tmp",
        "snapshot_5.pth.bodyrig-tmp",
    ],
)
def test_checkpoint_temp_cleanup_fails_closed_on_invalid_temp_name(
    tmp_path: Path,
    name: str,
) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / name).write_bytes(b"partial")

    with pytest.raises(adapter.ExAvatarTeacherAdapterError):
        adapter._cleanup_atomic_checkpoint_temps(model_dir)



def _complete_neutral_render_set(adapter, neutral_dir: Path) -> None:
    neutral_dir.mkdir(parents=True)
    for index in range(adapter.NEUTRAL_RENDER_COUNT):
        (neutral_dir / f"{index}.png").write_bytes(f"render-{index}".encode("utf-8"))
    (neutral_dir / "rgb.txt").write_text("rgb\n", encoding="utf-8")


def test_prepare_neutral_render_reuses_complete_render_set(tmp_path: Path) -> None:
    adapter = _load_adapter()
    neutral_dir = tmp_path / "neutral"
    _complete_neutral_render_set(adapter, neutral_dir)

    assert adapter._prepare_neutral_render(neutral_dir) is False
    assert (neutral_dir / "0.png").is_file()
    assert (neutral_dir / "rgb.txt").is_file()


def test_prepare_neutral_render_discards_only_partial_derived_output(tmp_path: Path) -> None:
    adapter = _load_adapter()
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()
    (neutral_dir / "0.png").write_bytes(b"partial")

    assert adapter._prepare_neutral_render(neutral_dir) is True
    assert neutral_dir.exists() is False

def test_training_finite_guard_upgrades_previous_probe_patch(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text(
        adapter.TRAIN_FINITE_PATCHED_V1
        + "\n"
        + adapter.TRAIN_STEP_PATCHED,
        encoding="utf-8",
    )

    result = adapter._ensure_training_finite_guard(path)
    patched = path.read_text(encoding="utf-8")

    assert result["applied"] is True
    assert adapter.TRAIN_FINITE_PATCHED_V1 not in patched
    assert adapter.TRAIN_FINITE_PATCHED in patched
    second = adapter._ensure_training_finite_guard(path)
    assert second["applied"] is False

