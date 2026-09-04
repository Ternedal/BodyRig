from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source() -> str:
    return (ROOT / "run-profiled-fidelity-convergence.ps1").read_text(encoding="utf-8")


def test_runner_exposes_explicit_resume_and_exact_checkpoint_validation() -> None:
    text = source()
    assert "[switch]$Resume" in text
    assert "bodyrig.fidelity_checkpoint" in text
    assert "bodyrig.fidelity_checkpoint_verify_cli" in text
    assert '"post-reconstruction"' in text
    assert '"post-candidate"' in text
    assert "checkpoint-" in text
    assert "rigSetupHash" in text
    assert "policyJson" in text


def test_checkpoint_binds_reconstruction_authority_sidecar() -> None:
    text = source()
    assert "reconstruction.json" in text
    assert "reconstruction-authority.json" in text


def test_resume_uses_active_compute_time_not_downtime_for_budget() -> None:
    text = source()
    assert "Get-ActiveElapsedSeconds" in text
    assert "activeElapsedBaseSeconds" in text
    assert "segmentStart" in text
    start = text.index("function WallClockAllowsAnotherFullRebuild")
    end = text.index("function Load-ResumeCheckpoint")
    assert "Get-ActiveElapsedSeconds" in text[start:end]


def test_checkpoint_is_published_only_after_prepublication_verification() -> None:
    text = source()
    verify = text.index("bodyrig.fidelity_checkpoint_verify_cli")
    publish = text.index("Move-Item -LiteralPath $checkpointTemp -Destination $checkpointPath")
    assert verify < publish
    assert "Write-CreateOnlyJson -Path $checkpointPath" not in text


def test_error_path_preserves_private_workspace_for_resume() -> None:
    text = source()
    start = text.index('} catch {\n    try { Update-Progress -State "error"')
    end = text.index("\n}\n\n$bestRecord", start) + 2
    catch = text[start:end]
    assert "preserving private workspace" in catch.lower()
    assert "Remove-PrivateWorkspaceIfNeeded" not in catch


def test_full_rebuild_cleanup_waits_for_newer_checkpoint() -> None:
    text = source()
    assert "$retiredIdentityWorkspace = $currentIdentityWorkspace" in text
    checkpoint = text.index('Write-FidelityCheckpoint -CheckpointStage "post-reconstruction"')
    cleanup = text.index("Remove-PrivateWorkspaceIfNeeded -Path $retiredIdentityWorkspace")
    assert checkpoint < cleanup
