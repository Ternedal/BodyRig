from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_status_docs_keep_wheel_inspection_separate_from_operator_authority() -> None:
    for path in (REPO / "README.md", REPO / "docs" / "RIG_ACCEPTANCE.md"):
        text = path.read_text(encoding="utf-8")
        assert "Inspection-only" in text
        assert "--operator-root" in text
        assert "HEAD" in text
        assert "git status --porcelain" in text
        assert "exit code `3`" in text
        assert "next_command" in text
