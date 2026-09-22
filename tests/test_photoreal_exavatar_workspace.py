from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_workspace as workspace


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialized_dataset(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    dataset = tmp_path / "dataset"
    frames = dataset / "frames"
    frames.mkdir(parents=True)
    frame = frames / "0.png"
    frame.write_bytes(b"png-frame")
    (dataset / "frame_list_all.txt").write_text("0\n", encoding="utf-8")
    (dataset / "frame_list_train.txt").write_text("0\n", encoding="utf-8")
    (dataset / "frame_list_test.txt").write_text("", encoding="utf-8")
    receipt: dict[str, object] = {
        "format": workspace.MATERIALIZATION_FORMAT,
        "version": 1,
        "benchmark_plan_sha256": "a" * 64,
        "teacher_input_sha256": "b" * 64,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "upstream_commit": workspace.UPSTREAM_COMMIT,
        "source_key": "scene:42:E:/train.mp4",
        "source_sha256": "c" * 64,
        "frame_count": 1,
        "frames": [
            {
                "exavatar_frame_index": 0,
                "source_key": "scene:42:E:/train.mp4",
                "source_frame_sha256": "d" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "relative_path": "frames/0.png",
                "staged_png_sha256": _sha(frame),
                "width": 1920,
                "height": 1080,
            }
        ],
        "frame_lists_are_training_only": True,
        "bodyrig_held_out_evaluation_is_external": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "exact_p0_frame_hashes_reproduced": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    return dataset, receipt


def _strict_preflight() -> dict[str, object]:
    value: dict[str, object] = {
        "format": workspace.PREFLIGHT_FORMAT,
        "version": 1,
        "upstream_commit": workspace.UPSTREAM_COMMIT,
        "smplx_gender": "female",
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "strict_upstream_asset_inventory": True,
        "strict_flame_asset_count": 3,
        "benchmark_environment_ready": True,
        "blockers": [],
        "automatic_restricted_asset_download": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "assets": [],
        "reference_vision_assets": [],
    }
    value["preflight_sha256"] = workspace._canonical_digest(value, omit="preflight_sha256")
    return value


def test_avatar_config_patch_forces_custom_and_explicit_female(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text(
        "class Config:\n"
        "    dataset = 'NeuMan' # Custom, NeuMan\n"
        "    smplx_gender = 'male' # only use male version as female version is not very good\n",
        encoding="utf-8",
    )

    receipt = workspace._patch_avatar_config(config, smplx_gender="female")
    patched = config.read_text(encoding="utf-8")

    assert "dataset = 'Custom'" in patched
    assert "smplx_gender = 'female'" in patched
    assert "smplx_gender = 'male'" not in patched
    assert receipt["dataset"] == "Custom"
    assert receipt["smplx_gender"] == "female"
    assert receipt["before_sha256"] != receipt["after_sha256"]


def test_materialization_validation_rejects_original_video(tmp_path: Path) -> None:
    dataset, receipt = _materialized_dataset(tmp_path)
    (dataset / "video.mp4").write_bytes(b"forbidden")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="original video.mp4"):
        workspace._validate_materialization(receipt, dataset)


def test_materialization_validation_rejects_nonempty_exavatar_test_split(tmp_path: Path) -> None:
    dataset, receipt = _materialized_dataset(tmp_path)
    (dataset / "frame_list_test.txt").write_text("0\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="test split"):
        workspace._validate_materialization(receipt, dataset)


def test_strict_preflight_requires_explicit_matching_female_prior() -> None:
    preflight = _strict_preflight()
    assert workspace._validate_preflight(preflight, smplx_gender="female") == preflight["preflight_sha256"]

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="gender mismatch"):
        workspace._validate_preflight(preflight, smplx_gender="male")


def test_preflight_without_strict_upstream_assets_cannot_prepare_workspace() -> None:
    preflight = _strict_preflight()
    preflight["strict_upstream_asset_inventory"] = False
    preflight["preflight_sha256"] = workspace._canonical_digest(preflight, omit="preflight_sha256")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="not strict-upstream complete"):
        workspace._validate_preflight(preflight, smplx_gender="female")


def test_safe_subject_id_is_deterministic_and_path_safe() -> None:
    assert workspace._safe_subject_id("42") == "bodyrig-42"
    assert workspace._safe_subject_id("performer/42") == "bodyrig-performer-42"


def test_workspace_git_uses_command_local_safe_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "ExAvatar_RELEASE"
    checkout.mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv, *, label):
        captured["argv"] = argv
        captured["label"] = label
        return workspace.UPSTREAM_COMMIT

    monkeypatch.setattr(workspace, "_run", fake_run)

    observed = workspace._git(checkout, "rev-parse", "HEAD")

    resolved = checkout.resolve()
    assert observed == workspace.UPSTREAM_COMMIT
    assert captured["argv"] == [
        "git",
        "-c",
        f"safe.directory={resolved}",
        "-C",
        str(resolved),
        "rev-parse",
        "HEAD",
    ]
