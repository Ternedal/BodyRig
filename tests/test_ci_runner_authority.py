from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_uses_explicit_major_os_runner_labels() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    regression = (
        ROOT / ".github" / "workflows" / "windows-log-handle-regression.yml"
    ).read_text(encoding="utf-8")

    assert "runs-on: ubuntu-24.04" in ci
    assert ci.count("runs-on: windows-2025") == 2
    assert "runs-on: windows-2025" in regression

    assert "runs-on: ubuntu-latest" not in ci
    assert "runs-on: windows-latest" not in ci
    assert "runs-on: windows-latest" not in regression
