from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_recovery_operator_brackets_both_modes_with_new_physical_session() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    start = source.index('"-m", "bodyrig.physical_session", "start"')
    readiness = source.index('"-m", "bodyrig.physical_session", "readiness-pass"')
    fitter = source.index('"-m", "bodyrig.external_fitter_cli"')
    fit_guard = source.rfind('if ($recoveryMode -eq "resume-fit-only")', 0, fitter)
    adopt_guard = source.index('elseif ($recoveryMode -eq "adopt-complete-package")', fitter)
    verify = source.index('bodyrig.interrupted_fit_recovery verify')
    passed = source.index('"-m", "bodyrig.physical_session", "pass"')
    assert start < readiness < fit_guard < fitter < adopt_guard < verify < passed
    assert "check-rig-ready.ps1" in source
    assert '$packagePath = Need-File -Path $packagePath -Label "Completed interrupted package"' in source


def test_recovery_reuses_existing_authority_and_never_restarts_clone_pipeline() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    assert "expensive_reconstruction_rerun = $false" in source
    assert "same completed SiTH reconstruction" in source
    assert "adopt already-complete verified package; no fitter or reconstruction rerun" in source
    assert "bodyrig.interrupted_fit_recovery plan" in source
    assert "bodyrig.interrupted_fit_recovery verify" in source
    assert "clone-body.ps1" not in source
    assert "clone-body-from-stash.ps1" not in source
    assert "bodyrig.recover_cli" not in source
    assert "bodyrig.identity_capture_cli" not in source


def test_recovery_receipt_distinguishes_adoption_from_fit_only_and_never_activates() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    assert "bodyrig.physical_session fail" in source
    assert '$recoveryStage = "readiness"' in source
    assert '$recoveryStage = "clone"' in source
    assert 'recovery_mode = $recoveryMode' in source
    assert 'fitter_rerun = ($recoveryMode -eq "resume-fit-only")' in source
    assert 'resumed_fit_only = ($recoveryMode -eq "resume-fit-only")' in source
    assert 'adopted_complete_package = ($recoveryMode -eq "adopt-complete-package")' in source
    assert "production_activation = $false" in source
    assert "human_visual_authority_required = $true" in source
    assert "complete-acceptance.ps1" not in source
    assert "complete-reference-renderer-acceptance" not in source


def test_recovery_verifier_binds_failed_inputs_package_and_reconstruction_authority() -> None:
    source = text("bodyrig/interrupted_fit_recovery.py")
    assert 'failed["status"] != "fail" or failed["stage"] != "clone"' in source
    assert 'failed["bodyrig_revision"] != current_revision' in source
    assert 'config["adapter"] != "sith-smplx-vrm"' in source
    assert 'ADOPT_COMPLETE_PACKAGE = "adopt-complete-package"' in source
    assert 'RESUME_FIT_ONLY = "resume-fit-only"' in source
    assert '"reconstruction_sha256": reconstruction_sha' in source
    assert "SiTH reconstruction authority changed during recovery" in source
    assert "complete interrupted package changed after recovery planning" in source
    assert "recovery authority changed during recovery" in source
