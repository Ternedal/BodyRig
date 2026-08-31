from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_recovery_operator_brackets_resumed_fit_with_new_physical_session() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    start = source.index('"-m", "bodyrig.physical_session", "start"')
    readiness = source.index('"-m", "bodyrig.physical_session", "readiness-pass"')
    fitter = source.index('"-m", "bodyrig.external_fitter_cli"')
    verify = source.index('bodyrig.interrupted_fit_recovery verify')
    passed = source.index('"-m", "bodyrig.physical_session", "pass"')
    assert start < readiness < fitter < verify < passed
    assert "check-rig-ready.ps1" in source


def test_recovery_reuses_existing_reconstruction_and_never_restarts_clone_pipeline() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    assert "expensive_reconstruction_rerun = $false" in source
    assert "same completed SiTH reconstruction" in source
    assert "bodyrig.interrupted_fit_recovery plan" in source
    assert "bodyrig.interrupted_fit_recovery verify" in source
    assert "clone-body.ps1" not in source
    assert "clone-body-from-stash.ps1" not in source
    assert "bodyrig.recover_cli" not in source
    assert "bodyrig.identity_capture_cli" not in source


def test_recovery_failure_is_recorded_and_never_creates_activation_authority() -> None:
    source = text("resume-interrupted-physical-fit.ps1")
    assert "bodyrig.physical_session fail" in source
    assert '$recoveryStage = "readiness"' in source
    assert '$recoveryStage = "clone"' in source
    assert "production_activation = $false" in source
    assert "human_visual_authority_required = $true" in source
    assert "complete-acceptance.ps1" not in source
    assert "complete-reference-renderer-acceptance" not in source


def test_recovery_verifier_binds_exact_failed_inputs_and_reconstruction_hash() -> None:
    source = text("bodyrig/interrupted_fit_recovery.py")
    assert 'failed["status"] != "fail" or failed["stage"] != "clone"' in source
    assert 'failed["bodyrig_revision"] != current_revision' in source
    assert 'config["adapter"] != "sith-smplx-vrm"' in source
    assert '"reconstruction_sha256": _sha256(reconstruction)' in source
    assert "SiTH reconstruction authority changed during recovery" in source
