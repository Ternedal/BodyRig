from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_one_command_preflights_gate_a_core_before_attempt_state_and_clone() -> None:
    source = _read("run-one-command-production-activation.ps1")
    core = '$acceptCoreScript = Join-Path $repoRoot "accept-physical-clone-core.ps1"'
    dependency_set = '@($cloneScript, $acceptScript, $acceptCoreScript, $activateScript)'
    assert core in source
    assert dependency_set in source
    assert source.index(core) < source.index('New-Item -ItemType Directory -Path $RunRoot')
    assert source.index(core) < source.index('& $cloneScript @cloneArgs')


def test_profiled_convergence_preflights_gate_a_core_before_workroot_and_rebuild() -> None:
    source = _read("run-profiled-fidelity-convergence.ps1")
    core = '[void](Resolve-InputFile -Path (Join-Path $repoRoot "accept-physical-clone-core.ps1") -Label "Gate A transactional core")'
    assert core in source
    assert source.index(core) < source.index('New-Item -ItemType Directory -Path $WorkRoot')
    assert source.index(core) < source.index('& $profileLauncher @cloneArgs')


def test_interrupted_recovery_preflights_gate_a_core_before_plan_and_fitter_when_requested() -> None:
    source = _read("resume-interrupted-physical-fit.ps1")
    wrapper = '$gateA = Need-File -Path (Join-Path $repoRoot "accept-physical-clone.ps1") -Label "Gate A launcher"'
    core = '[void](Need-File -Path (Join-Path $repoRoot "accept-physical-clone-core.ps1") -Label "Gate A transactional core")'
    assert wrapper in source
    assert core in source
    assert source.count(wrapper) == 1
    assert source.count(core) == 1
    assert source.index(core) < source.index('$planRaw = @(')
    assert source.index(core) < source.index('"-m", "bodyrig.external_fitter_cli"')
    assert source.index(core) < source.index('Write-CreateOnlyJson -Path $RecoveryReceipt -Value $receipt')
