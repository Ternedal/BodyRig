from __future__ import annotations

from pathlib import Path


HANDOFF = (Path(__file__).resolve().parents[1] / "HANDOFF.md").read_text(encoding="utf-8")


def test_handoff_exposes_canonical_repository_authority_admin_helper() -> None:
    assert "configure-repository-authority.ps1" in HANDOFF
    assert ".\\configure-repository-authority.ps1 -Apply" in HANDOFF
    assert "dry run" in HANDOFF.lower()
    assert "app_id=15368" in HANDOFF
    assert "verify-repository-authority.ps1" in HANDOFF


def test_handoff_keeps_repository_and_physical_authority_separate() -> None:
    assert "issue #138 remains open" in HANDOFF
    assert "Software, CI or physical evidence cannot substitute" in HANDOFF
    assert "does not create physical/human PASS" in HANDOFF
