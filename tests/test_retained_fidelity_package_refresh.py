from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "refresh-retained-fidelity-candidate.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_refresh_uses_retained_sith_without_reconstruction_launcher() -> None:
    text = source()

    assert '"sith-input-v1\\reconstruction.json"' in text
    assert '"sith-input-v1\\reconstruction-authority.json"' in text
    assert '"sith-input-v1\\meshes\\000_reco.obj"' in text
    assert '"sith-input-v1\\smplx\\000_smplx.obj"' in text
    assert '"sith-input-v1\\smplx\\000_fit.json"' in text
    assert '"-m", "bodyrig.external_fitter_cli"' in text
    assert "expensive_reconstruction_rerun = $false" in text
    assert "fitter_rerun = $true" in text

    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence",
        '"-m", "bodyrig.sith_reconstruct"',
        "reconstruct_sith(",
        "SithSeed",
    ):
        assert forbidden not in text


def test_refresh_requires_current_physical_floor_exact_checkout_python_and_builder_revision() -> None:
    text = source()

    assert "MINIMUM_PHYSICAL_HANDOFF_REVISION" in text
    assert "merge-base --is-ancestor $floor $head" in text
    assert "does not meet the physical fidelity floor" in text
    assert "pathlib,bodyrig" in text
    assert "BodyRig Python imports bodyrig from a different checkout/package" in text
    assert "checkout_bound_bodyrig_module = $actualBodyRigModule" in text
    assert "Refreshed package builder revision is not the exact current checkout." in text
    assert "minimum_physical_handoff_revision = $floor" in text
    assert "refreshed_builder_revision = [string]$refreshed.builder_revision" in text


def test_refresh_rehydrates_historical_fitter_command_onto_current_python() -> None:
    text = source()

    assert '"bodyrig-external-fitter-config"' in text
    assert "Test-V1Version $fitter.version" in text
    assert '[string]$fitter.adapter -ne "sith-smplx-vrm"' in text
    assert '[string]$fitterCommand[1] -ne "-m"' in text
    assert '[string]$fitterCommand[2] -ne "bodyrig.sith_fitter_orchestrator"' in text
    assert "$rehydratedCommand = @($BodyRigPython)" in text
    assert '"--config", $currentFitterConfig' in text
    assert "baseline_fitter_config_sha256 = $baselineFitterConfigShaBefore" in text
    assert "current_fitter_config_sha256 = $currentFitterConfigSha" in text


def test_refresh_rehydrates_reboot_safe_sith_resume_environment_from_validated_authority() -> None:
    text = source()

    assert "[string]$RigSetupReport" in text
    assert '"BODYRIG_RIG_SETUP_REPORT"' in text
    assert '"BodyRig\\bodyrig-rig-setup.json"' in text
    assert "-m bodyrig.rig_setup $RigSetupReport" in text
    assert "-m bodyrig.sith_setup $sithSetupReport" in text
    assert "$sith.checkpoints.recon_model.sha256" in text
    assert "$sith.checkpoints.smplerx.sha256" in text
    assert '"bodyrig-sith-reconstruction-authority"' in text
    assert "validate_reconstruction_authority" in text
    assert '"BODYRIG_SITH_RECON_CHECKPOINT_SHA256"' in text
    assert '"BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256"' in text
    assert '"BODYRIG_SITH_BODY_MODEL_GENDER"' in text
    assert "$previousEnvironment = @{}" in text
    assert "Remove-Item -Path \"Env:$name\"" in text
    assert "rig_setup_sha256 = $rigSetupSha" in text
    assert "sith_setup_sha256 = $sithSetupSha" in text
    assert "body_model_gender = $bodyModelGender" in text


def test_refresh_hash_binds_all_reused_authority_before_and_after_fitter() -> None:
    text = source()

    for variable in (
        "$reconstructionShaBefore",
        "$reconstructionAuthorityShaBefore",
        "$sourceMeshShaBefore",
        "$donorShaBefore",
        "$fitShaBefore",
        "$sourcePackageSha",
        "$proofShaBefore",
        "$identityShaBefore",
        "$portableIdentityShaBefore",
        "$baselineFitterConfigShaBefore",
    ):
        assert variable in text
    assert "Retained current-floor refresh authority inputs changed during fitter execution." in text
    assert "Move-Item -LiteralPath $attempt -Destination $OutputDir" in text
    assert "if (-not $committed" in text


def test_refresh_reuses_exact_proof_bound_adjustment_evidence_without_regeneration() -> None:
    text = source()

    assert "[string]$AdjustmentEvidence" in text
    assert 'load_adjustment_evidence(sys.argv[1], proof_path=sys.argv[2])' in text
    assert '"--bodyprint-adjustment", $adjustmentEvidenceCopy' in text
    assert "Adjusted current-floor refresh does not preserve the exact selected adjustment evidence provenance." in text
    assert "adjustment_evidence_sha256 = $adjustmentEvidenceSha" in text
    assert "bodyrig.bodyprint_adjustment\", \"bind" not in text
    assert "AdjustmentRequest" not in text


def test_refresh_preserves_identity_and_never_claims_visual_or_production_acceptance() -> None:
    text = source()

    assert '"--portable-identity", $portableIdentity' in text
    assert "Refreshed package changed canonical body identity." in text
    assert "comparison_only = $true" in text
    assert "human_visual_authority_required = $true" in text
    assert "production_activation = $false" in text
    assert 'semantics = "current-floor-refit-repackage-from-retained-sith-with-checkout-bound-fitter-not-reconstruction"' in text
    assert "human visual review required" in text
