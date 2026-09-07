from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOP = (ROOT / "run-automatic-production-activation.ps1").read_text(encoding="utf-8")
QUEST = (ROOT / "run-automatic-reference-quest-proof.ps1").read_text(encoding="utf-8")
COMPLETE = (ROOT / "complete-automatic-reference-acceptance.ps1").read_text(encoding="utf-8")
ONE_COMMAND = (ROOT / "run-one-command-production-activation.ps1").read_text(encoding="utf-8")


def test_top_automatic_activation_is_stage_driven_and_bounded() -> None:
    assert "bodyrig.automatic_activation_status" in TOP
    assert "for ($transition = 0; $transition -lt 4; $transition++)" in TOP
    assert '"windows" {' in TOP
    assert '"quest" {' in TOP
    assert '"quest-quality" {' in TOP
    assert '"release" {' in TOP
    assert '[string]$after.stage -eq $stage' in TOP
    assert "refusing an unbounded retry" in TOP


def test_top_automatic_activation_reuses_existing_complete_receipt() -> None:
    status = TOP.index("$status = Get-AutomaticActivationStatus")
    complete = TOP.index('[string]$status.state -eq "complete"')
    windows = TOP.index('"windows" {')
    assert status < complete < windows
    assert 'Write-Host "production_activation=true"' in TOP


def test_automatic_activation_uses_checkout_bound_bodyrig_python() -> None:
    for source in (TOP, QUEST, COMPLETE):
        assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in source
        assert 'import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())' in source
        assert "Expected checkout authority" in source
    assert "Get-Command python" not in COMPLETE


def test_quest_quality_recovery_reuses_committed_probe_pair_without_renderer_rebuild() -> None:
    assert "$recoverQualityOnly = $probeExists -and $deformationExists" in QUEST
    assert '[string]$before.stage -ne "quest-quality"' in QUEST
    assert "reusing committed probe/deformation; recovering quality receipt only" in QUEST
    recovery = QUEST.index("if ($recoverQualityOnly)")
    fresh = QUEST.index("} else {", recovery)
    inner = QUEST.index("& $inner @args", fresh)
    assert recovery < fresh < inner
    assert "Quest renderer rebuild: skipped" in QUEST


def test_quest_quality_recovery_never_commits_unvalidated_quality() -> None:
    assert "$qualityCommitted = $false" in QUEST
    assert "Move-Item -LiteralPath $temp -Destination $localQuality" in QUEST
    assert "$after = Get-AutomaticStatus" in QUEST
    assert '[string]$after.stage -notin @("release", "complete")' in QUEST
    assert "Remove-Item -LiteralPath $localQuality -Force" in QUEST


def test_quest_quality_recovery_can_relaunch_installed_app_without_rebuild() -> None:
    assert "Wait-RemoteQuality -RelaunchIfMissing" in QUEST
    assert "relaunching the already-installed exact reference app without rebuilding" in QUEST
    assert 'Invoke-Adb -Arguments @("shell", "monkey", "-p", $script:ApplicationId, "1")' in QUEST


def test_final_automatic_gate_receives_same_checkout_python() -> None:
    assert '$completeArgs = @{ AcceptanceDir = $AcceptanceDir; Output = $releaseOutput; BodyRigPython = $BodyRigPython }' in TOP
    assert '& $BodyRigPython @args' in COMPLETE


def test_one_command_forwards_explicit_bodyrig_python_to_resumable_activation() -> None:
    assert 'if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $activateArgs.BodyRigPython = $BodyRigPython }' in ONE_COMMAND
