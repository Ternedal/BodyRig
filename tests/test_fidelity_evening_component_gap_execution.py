from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_exposes_explicit_context_and_one_step_opt_in() -> None:
    text = source()
    assert '[string]$ExecutionContext = ""' in text
    assert '[switch]$ExecuteNextAction' in text
    assert 'bodyrig.fidelity_component_gap_executor' in text
    assert '"--plan", $PlanPath' in text
    assert '"--context", $ContextPath' in text
    assert '"--repo-root", $RepoRoot' in text
    assert 'if ($Execute) { $arguments += "--execute" }' in text
    assert '-Execute:$ExecuteNextAction' in text
    assert 'BODYRIG ONE QUALIFIED COMPONENT-GAP STEP EXECUTED' in text
    assert 'Rerun this evening command to recompute physical evidence before any further action.' in text


def test_evening_empty_context_does_not_invent_hfn_identity_or_source_fields() -> None:
    text = source()
    assert '[IO.File]::WriteAllText($temporaryExecutionContext, "{}"' in text
    assert '$contextPath = Need-File -Path $ExecutionContext' in text
    for forbidden in (
        'person-',
        'hfncap-',
        'hfncand-',
        'body-r0001',
        'UvEvidence',
        'CaptureId',
    ):
        assert forbidden not in text


def test_evening_validates_executor_against_exact_final_gap_authority() -> None:
    text = source()
    assert '[string]$Value.bodyrig_revision -ne $ExpectedHead' in text
    assert '[string]$Value.body_id -ne $ExpectedBodyId' in text
    assert '[string]$Value.source_gap_package_sha256 -ne $ExpectedPackageSha' in text
    assert '[string]$Value.action_id -ne $ExpectedActionId' in text
    assert '$Value.human_visual_authority_required -ne $true' in text
    assert '$Value.production_activation -ne $false' in text
    assert '-ExpectedPackageSha $physicalPackageSha' in text
    assert '-ExpectedActionId $expectedActionId' in text


def test_evening_surfaces_operator_stop_and_never_executes_human_action_itself() -> None:
    text = source()
    assert 'if ($executionMode -eq "operator-stop")' in text
    assert 'Executor stop:' in text
    assert 'operator_command' in text
    assert 'Invoke-Expression' not in text
    assert 'record-high-fidelity-hfn-review.ps1' not in text
    assert 'record-high-fidelity-human-review.ps1' not in text


def test_evening_execution_stops_before_presenting_stale_post_step_gap() -> None:
    text = source()
    executed = text.index('BODYRIG ONE QUALIFIED COMPONENT-GAP STEP EXECUTED')
    exit_after = text.index('exit 0', executed)
    normal_result = text.index('BODYRIG EVENING RESULT')
    assert executed < exit_after < normal_result
    assert 'Reprobe required: TRUE' in text[executed:exit_after]
    assert 'Production:      FALSE' in text[executed:exit_after]
