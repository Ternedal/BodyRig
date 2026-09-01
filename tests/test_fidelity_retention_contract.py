from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-profiled-fidelity-convergence.ps1"


def test_full_rebuild_always_retains_private_workspace_until_checkpoint() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '$cloneArgs = @{' in source
    assert 'KeepPrivateWorkspace = $true' in source
    assert '& $profileLauncher @cloneArgs' in source
    assert '$cloneArgs = @(' not in source
    assert 'Write-FidelityCheckpoint -CheckpointStage "post-reconstruction"' in source


def test_operator_retention_switch_controls_terminal_cleanup() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '[switch]$KeepPrivateWorkspaces' in source
    assert 'if (-not $KeepPrivateWorkspaces' in source
    assert 'Remove-PrivateWorkspaceIfNeeded -Path $currentIdentityWorkspace' in source
    assert 'Remove-PrivateWorkspaceIfNeeded -Path $retiredIdentityWorkspace' in source


def test_checkpoint_binds_reconstruction_and_identity_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Join-Path $currentIdentityWorkspace "sith-input-v1\\reconstruction.json"' in source
    assert 'current_identity_workspace = [IO.Path]::GetFullPath($currentIdentityWorkspace)' in source
    assert 'expensive_reconstruction_rerun = $false' in (ROOT / "refit-fidelity-candidate.ps1").read_text(encoding="utf-8")
