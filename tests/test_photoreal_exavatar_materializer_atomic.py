from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_exavatar_materializer as materializer
from bodyrig.photoreal_teacher_benchmark_plan import build_teacher_benchmark_plan


def _teacher_input() -> dict[str, object]:
    key = "scene:scan:E:/scan.mp4"
    observations = [
        {
            "source_key": key,
            "group_id": "scene:scan",
            "split": "train",
            "frame_sha256": "1" * 64,
            "timestamp_seconds": 1.25,
            "eye": "mono",
            "view_bin": "front",
            "coverage": ["face-front", "full-body-front"],
        },
        {
            "source_key": key,
            "group_id": "scene:scan",
            "split": "train",
            "frame_sha256": "2" * 64,
            "timestamp_seconds": 2.5,
            "eye": "mono",
            "view_bin": "three-quarter-left",
            "coverage": ["face-three-quarter", "full-body-three-quarter"],
        },
    ]
    return {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "d" * 64,
        "training_sources": [
            {
                "source_key": key,
                "group_id": "scene:scan",
                "kind": "video",
                "resolved_path": r"\\stash\VR_E\scan.mp4",
                "size_bytes": 1000,
                "sha256": "a" * 64,
                "information_score": 100.0,
                "width": 3840,
                "height": 2160,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "training_observations": observations,
        "training_source_count": 1,
        "training_observation_count": 2,
        "held_out_evaluation_sources": [{"source_key": "scene:e:E:/secret.mp4"}],
        "held_out_evaluation_observations": [{"frame_sha256": "e" * 64}],
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _converter(path: str) -> str:
    return "/bodyrig/" + Path(path.replace("\\", "/")).name


def test_materializer_cleans_staging_after_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    workspace = tmp_path / "workspace"
    stage = workspace.with_name(f".{workspace.name}.stage")
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")

    monkeypatch.setattr(materializer, "make_wsl_path_converter", lambda _exe, _distribution: _converter)

    def fake_run(_invocation, **_kwargs):
        frames = stage / "dataset" / "frames"
        frames.mkdir(parents=True)
        (frames / "0.png").write_bytes(b"partial")
        return SimpleNamespace(returncode=7, stdout="synthetic failure\n")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    with pytest.raises(materializer.PhotorealExAvatarMaterializerError, match="failed with exit code 7"):
        materializer.materialize_exavatar_benchmark(plan, workspace=workspace, tool_path=tool)

    assert not workspace.exists()
    assert not stage.exists()


def test_materializer_refuses_non_directory_staging_path(tmp_path: Path) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    workspace = tmp_path / "workspace"
    stage = workspace.with_name(f".{workspace.name}.stage")
    stage.write_text("do not delete", encoding="utf-8")
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")

    with pytest.raises(materializer.PhotorealExAvatarMaterializerError, match="staging path is not a directory"):
        materializer.materialize_exavatar_benchmark(plan, workspace=workspace, tool_path=tool)

    assert stage.read_text(encoding="utf-8") == "do not delete"
