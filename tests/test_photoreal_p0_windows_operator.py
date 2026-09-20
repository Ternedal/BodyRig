from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "run-photoreal-p0-windows.ps1").read_text(encoding="utf-8")


def test_p0_operator_is_fail_closed_and_never_reconstructs() -> None:
    assert 'git -C $repoRoot status --porcelain' in SCRIPT
    assert 'Photoreal P0 requires an exact clean BodyRig checkout.' in SCRIPT
    assert 'Production:        FALSE' in SCRIPT
    assert 'Photoreal accept:  FALSE' in SCRIPT
    assert 'human_visual_acceptance_required = $true' in SCRIPT
    assert 'production_activation = $false' in SCRIPT
    assert 'bodyrig.sith_' not in SCRIPT
    assert 'reference-renderer' not in SCRIPT
    assert 'Vrm' not in SCRIPT


def test_p0_operator_runs_authority_chain_in_order() -> None:
    ordered_modules = [
        'bodyrig.photoreal_dataset_plan_cli',
        'bodyrig.photoreal_source_verify_cli',
        'bodyrig.photoreal_scan_plan_cli',
        'bodyrig.photoreal_identity_bootstrap_cli',
        'bodyrig.photoreal_model_set_cli',
        'bodyrig.photoreal_identity_extractor_cli',
        'bodyrig.photoreal_identity_bank_cli',
        'bodyrig.photoreal_identity_negative_inventory_cli',
        'bodyrig.photoreal_identity_negative_verify_cli',
        'bodyrig.photoreal_identity_calibration_plan_cli',
        'bodyrig.photoreal_identity_calibration_extractor_cli',
        'bodyrig.photoreal_identity_calibration_cli',
        'bodyrig.photoreal_frame_analyzer_cli',
        'bodyrig.photoreal_frame_identity_authority_cli',
        'bodyrig.photoreal_frame_index_cli',
    ]
    positions = [SCRIPT.index(module) for module in ordered_modules]
    assert positions == sorted(positions)
    assert '--authorized-observations' in SCRIPT


def test_source_only_can_never_grant_teacher_training_authority() -> None:
    source_only = SCRIPT.index('if ($SourceOnly)')
    source_block = SCRIPT[source_only : SCRIPT.index('Invoke-PythonStage -Label "6/16', source_only)]
    assert 'TeacherTrainingAuthorized $false' in source_block
    assert 'Teacher training: BLOCKED' in source_block
    assert 'exit 2' in source_block


def test_python_stage_captures_stdout_before_returning_exit_code() -> None:
    stage_start = SCRIPT.index('function Invoke-PythonStage')
    stage_end = SCRIPT.index('$repoRoot =', stage_start)
    stage = SCRIPT[stage_start:stage_end]
    assert '$stageOutput = @(& $script:Python @Arguments)' in stage
    assert '$code = $LASTEXITCODE' in stage
    assert 'foreach ($line in $stageOutput)' in stage
    assert 'return $code' in stage


def test_p0_operator_requires_pinned_model_and_adapter_inputs_for_full_mode() -> None:
    assert 'Photoreal analyzer model root' in SCRIPT
    assert 'Photoreal identity extractor config' in SCRIPT
    assert 'Photoreal frame analyzer config' in SCRIPT
    assert 'PIN ANALYZER MODEL SET' in SCRIPT


def test_calibration_block_does_not_preempt_source_bound_identity() -> None:
    calibration = SCRIPT.index('if ($calibrationExit -eq 2)')
    frame_analysis = SCRIPT.index('14/16 MEASURE ALL PLANNED FRAMES', calibration)
    block = SCRIPT[calibration:frame_analysis]

    assert 'BLOCKED FOR BIOMETRIC MATCHING' in block
    assert 'Source-bound identity: CONTINUING' in block
    assert 'single-performer Stash sources are independently authorized by source binding' in block
    assert 'exit 2' not in block
    assert 'Write-Status -Status "identity-calibration-blocked"' not in block


def test_source_authority_still_runs_after_uncalibrated_matcher() -> None:
    calibration = SCRIPT.index('13/16 DERIVE IDENTITY THRESHOLD')
    frame_analysis = SCRIPT.index('14/16 MEASURE ALL PLANNED FRAMES')
    identity_authority = SCRIPT.index('15/16 APPLY CORE IDENTITY AUTHORITY')
    frame_index = SCRIPT.index('16/16 LEAKAGE + HELD-OUT COVERAGE GATE')

    assert calibration < frame_analysis < identity_authority < frame_index
    assert 'bodyrig.photoreal_frame_identity_authority_cli' in SCRIPT[identity_authority:frame_index]
