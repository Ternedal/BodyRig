from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ONE_COMMAND = (ROOT / "run-one-command-production-activation.ps1").read_text(encoding="utf-8")
STATUS = (ROOT / "physical-acceptance-status.ps1").read_text(encoding="utf-8")
DISCOVERY = (ROOT / "bodyrig" / "automatic_run_discovery.py").read_text(encoding="utf-8")
RECOVERY = (ROOT / "bodyrig" / "one_command_recovery.py").read_text(encoding="utf-8")


def test_one_command_only_publishes_recovery_after_unique_producer_validation() -> None:
    assert 'Join-Path $artifactBase "BodyRig\\identity-workspaces"' in ONE_COMMAND
    assert "$identityBefore" in ONE_COMMAND
    assert "bodyrig.interrupted_fit_recovery plan" in ONE_COMMAND
    assert "$matches.Count -eq 1" in ONE_COMMAND
    assert "$matches.Count -gt 1" in ONE_COMMAND
    assert 'Join-Path $RunRoot "interrupted-fit-recovery-plan.json"' in ONE_COMMAND
    assert 'interrupted_fit_recovery_plan_sha256' in ONE_COMMAND
    assert 'identity_workspace' in ONE_COMMAND
    assert 'expensive_reconstruction_rerun' in ONE_COMMAND
    assert 'fitter_rerun' in ONE_COMMAND
    assert "throw $cloneFailure" in ONE_COMMAND


def test_interrupted_assessment_mirrors_supported_bodyrig_python_fallback() -> None:
    venv = ONE_COMMAND.index('Join-Path $repoRoot ".venv\\Scripts\\python.exe"')
    system_python = ONE_COMMAND.index("Get-Command python -ErrorAction SilentlyContinue", venv)
    import_proof = ONE_COMMAND.index("import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())", system_python)
    assert venv < system_python < import_proof
    assert "if ($null -ne $pythonCommand) { $recoveryPython = $pythonCommand.Source }" in ONE_COMMAND


def test_one_command_success_path_does_not_force_private_workspace_retention() -> None:
    # clone-body.ps1 already retains the identity workspace on failure and removes
    # it on success. The one-command wrapper must not broaden successful-run
    # private-data retention merely to make failures recoverable.
    assert "$cloneArgs.KeepPrivateWorkspace" not in ONE_COMMAND
    assert "-KeepPrivateWorkspace" not in ONE_COMMAND


def test_status_dispatches_one_command_recovery_before_legacy_session_status() -> None:
    recovery = STATUS.index('"-m", "bodyrig.one_command_recovery"')
    fallback = STATUS.index('"-m", "bodyrig.acceptance_status_cli"')
    assert recovery < fallback
    assert "$recoveryExit -eq 0" in STATUS
    assert "$recoveryExit -ne 3" in STATUS
    assert "exit $recoveryExit" in STATUS


def test_structural_discovery_never_promotes_failed_session_without_recovery_receipt() -> None:
    assert "inspect_one_command_recovery(session_path)" in DISCOVERY
    assert "if recovery is None:" in DISCOVERY
    assert "return None" in DISCOVERY
    assert '"expensive_reconstruction_rerun": False' in DISCOVERY


def test_live_recovery_revalidates_with_producer_plan_before_emitting_command() -> None:
    structural = RECOVERY.index("structural = inspect_one_command_recovery(session_report)")
    semantic = RECOVERY.index("live = build_recovery_plan(", structural)
    command = RECOVERY.index('".\\\\resume-interrupted-physical-fit.ps1 "', semantic)
    assert structural < semantic < command
    assert '"status", "--porcelain"' in RECOVERY
    assert "one-command recovery requires an exact clean producer checkout" in RECOVERY
    assert "producer recovery mode changed since the persisted recovery plan" in RECOVERY
