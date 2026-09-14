from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_exposes_explicit_context_and_one_step_switch() -> None:
    text = source()
    assert '[string]$ComponentGapContext = ""' in text
    assert '[switch]$ExecuteQualifiedNextAction' in text
    assert "ExecuteQualifiedNextAction requires an explicit ComponentGapContext" in text
    assert "will not invent package/workspace/HFN source authority" in text


def test_evening_routes_exact_final_gap_through_existing_executor() -> None:
    text = source()
    gap_read = text.index('$gap = Read-Json -Path $gapPath -Label "Current-floor component gap plan"')
    gap_guard = text.index('[string]$gap.package_sha256 -ne $physicalPackageSha', gap_read)
    executor = text.index('"bodyrig.fidelity_component_gap_executor"', gap_guard)
    result = text.index('Write-Host "BODYRIG EVENING RESULT"', executor)
    assert gap_read < gap_guard < executor < result
    assert '"--plan", $gapPath' in text
    assert '"--context", $componentGapContextPath' in text
    assert '"--repo-root", $repoRoot' in text


def test_evening_fail_closed_validates_executor_authority() -> None:
    text = source()
    for marker in (
        '"bodyrig-fidelity-component-gap-execution"',
        'Test-V1Version $qualifiedGapExecution.version',
        '[string]$qualifiedGapExecution.bodyrig_revision -ne $head',
        '[string]$qualifiedGapExecution.source_gap_package_sha256 -ne $physicalPackageSha',
        '[string]$qualifiedGapExecution.action_id -ne [string]$firstAction.id',
        '$qualifiedGapExecution.human_visual_authority_required -ne $true',
        '$qualifiedGapExecution.production_activation -ne $false',
        '"execute-one-machine-safe-component-gap-action-then-reprobe"',
    ):
        assert marker in text


def test_evening_executes_at_most_one_machine_safe_action_then_stops_for_reprobe() -> None:
    text = source()
    assert 'if ($ExecuteQualifiedNextAction -and $executorMode -eq "machine-executable")' in text
    assert '$executeArgs += "--execute"' in text
    assert text.count('$executeArgs += "--execute"') == 1
    assert "Executed exactly one qualified machine-safe component-gap action." in text
    assert "Fresh Unity/component status is required before another action; re-run the evening command." in text
    execute_pos = text.index('$executeArgs += "--execute"')
    exit_pos = text.index("exit 0", execute_pos)
    final_result = text.index('Write-Host "BODYRIG EVENING RESULT"', execute_pos)
    assert execute_pos < exit_pos < final_result


def test_evening_preserves_operator_and_human_stops() -> None:
    text = source()
    assert '$executorMode -eq "operator-stop"' in text
    assert '$qualifiedGapExecution.operator_input_required -ne $true' in text
    assert '$qualifiedGapExecution.reprobe_required_after_execution -ne $false' in text
    assert 'Write-Host "Executor stop: $([string]$qualifiedGapExecution.reason)"' in text
    assert 'Write-Host "Operator command: $operatorCommand"' in text
    assert "Execution: BLOCKED at explicit operator/human authority boundary." in text
    assert "Human visual QA: REQUIRED" in text
    assert "Production:      FALSE" in text


def test_evening_checks_checkout_after_machine_execution() -> None:
    text = source()
    execute_pos = text.index('$executeArgs += "--execute"')
    assert text.index("git -C $repoRoot rev-parse HEAD", execute_pos) > execute_pos
    assert text.index("git -C $repoRoot status --porcelain", execute_pos) > execute_pos
    assert "BodyRig checkout changed during qualified component-gap execution." in text


def test_evening_does_not_directly_implement_hfn_or_human_actions() -> None:
    text = source()
    for forbidden in (
        "prepare-hands-feet-nails-detail-candidate.ps1",
        "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
        "prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
        "record-high-fidelity-hfn-review.ps1",
        "record-high-fidelity-human-review.ps1",
    ):
        assert forbidden not in text
