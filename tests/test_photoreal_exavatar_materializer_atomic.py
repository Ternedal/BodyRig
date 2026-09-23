from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_exavatar_materializer as materializer
from bodyrig.photoreal_teacher_benchmark_plan import build_teacher_benchmark_plan
from tests.test_photoreal_exavatar_materializer import _teacher_input


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
