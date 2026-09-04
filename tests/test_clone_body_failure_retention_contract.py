from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "clone-body.ps1").read_text(encoding="utf-8")


def test_failed_clone_retains_private_identity_workspace_for_recovery() -> None:
    assert 'Private identity workspace retained after failed build for recovery:' in SCRIPT
    assert 'Private identity workspace deleted after failed build.' not in SCRIPT


def test_successful_clone_still_deletes_private_identity_workspace_by_default() -> None:
    assert 'if ($success -and -not $KeepPrivateWorkspace' in SCRIPT
    assert 'Private identity workspace deleted after successful package build.' in SCRIPT


def test_explicit_keep_still_wins_on_success() -> None:
    assert 'elseif ($KeepPrivateWorkspace -and (Test-Path -LiteralPath $PrivateWorkspace -PathType Container))' in SCRIPT
    assert 'Private identity workspace retained by explicit request:' in SCRIPT
