from __future__ import annotations

import tomllib
from pathlib import Path


def test_test_extra_declares_starlette_testclient_runtime() -> None:
    repo = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["optional-dependencies"]["test"]

    assert any(item.startswith("httpx2>=") for item in dependencies)
