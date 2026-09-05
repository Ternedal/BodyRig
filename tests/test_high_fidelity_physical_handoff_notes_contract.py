from __future__ import annotations

from pathlib import Path


def test_scratch_notes_forbid_parallel_authority() -> None:
    text = (Path(__file__).resolve().parents[1] / "PHYSICAL-HANDOFF-NOTES.md").read_text(encoding="utf-8")
    assert "temporary" in text.lower()
    assert "must not become a new integration authority" in text
    assert "folded back into PR #83" in text
