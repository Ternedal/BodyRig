from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_authority_documentation_keeps_platform_roles_distinct() -> None:
    text = (ROOT / "docs" / "DEPENDENCY_AUTHORITY.md").read_text(encoding="utf-8")

    assert "windows-python.lock.txt" in text
    assert "Windows rig/operator/test runtime" in text
    assert "linux-ci-python.lock.txt" in text
    assert "Ubuntu CI dependency set" in text
    assert "colorama" in text
    assert "uvloop" in text
    assert "does not create or rebind physical/human evidence" in text
