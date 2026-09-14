from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening-current-floor-review.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_current_floor_review_uses_history_only_for_candidate_selection() -> None:
    text = source()

    assert "=== 1/4 HISTORICAL V5 SELECTION ===" in text
    assert "run-fidelity-v5-review.ps1" in text
    assert "Get-ExactIteration -Value $decision.best_iteration" in text
    assert "$Value -is [bool]" in text
    assert "Historical selected package bytes differ from the candidate bytes scored by V5." in text
    assert "historical_selected_package_sha256" in text


def test_current_floor_review_refreshes_selected_candidate_before_physical_preview() -> None:
    text = source()

    assert "refresh-retained-fidelity-candidate.ps1" in text
    assert "=== 2/4 CURRENT-FLOOR REFIT/REPACKAGE (NO SITH RECONSTRUCTION) ===" in text
    assert "current_floor_refit_repackage = $true" in text
    assert "expensive_reconstruction_rerun = $false" in text
    assert "refreshed_builder_revision" in text
    assert "Current-floor package bytes/revision differ from refresh authority." in text
    assert "PackagePath = $currentPackage" in text
    assert "PackagePath = $historicalPackage" not in text


def test_current_floor_review_reuses_exact_historical_refit_adjustment_evidence() -> None:
    text = source()

    assert '"bodyrig-bodyprint-adjustment.json"' in text
    assert "Historical refit adjustment evidence bytes differ from refit-result authority." in text
    assert "$refreshArgs.AdjustmentEvidence = $selectedAdjustmentEvidence" in text
    assert "adjustment_evidence_sha256" in text
    assert "Current-floor refresh does not preserve the selected adjustment evidence authority." in text
    assert "AdjustmentRequest" not in text


def test_current_floor_review_binds_refresh_reuse_to_source_body_reconstruction_and_adjustment() -> None:
    text = source()

    assert "ExpectedSourcePackageSha" in text
    assert "ExpectedBodyAlias" in text
    assert "ExpectedAdjustmentEvidenceSha" in text
    assert '[string]$receipt.source_package_sha256 -ne $ExpectedSourcePackageSha' in text
    assert '[string]$receipt.body_alias -ne $ExpectedBodyAlias' in text
    assert '[string]$receipt.adjustment_evidence_sha256 -ne $ExpectedAdjustmentEvidenceSha' in text


def test_current_floor_review_never_starts_sith_reconstruction() -> None:
    text = source()

    assert "SiTH reconstruction: NEVER STARTED BY THIS RUNNER" in text
    assert "Current-floor fitter/repackage: ALLOWED" in text
    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence.ps1",
        "sith_reconstruct",
        "SithSeed",
    ):
        assert forbidden not in text


def test_current_floor_review_requires_checkout_bound_python() -> None:
    text = source()

    assert "Assert-CheckoutBoundPython" in text
    assert "pathlib,bodyrig" in text
    assert "BodyRig Python imports bodyrig from a different checkout/package" in text
    assert "checkout changed during current-floor evening review" in text
    assert "checkout became dirty during current-floor evening review" in text


def test_current_floor_review_validates_component_evidence_through_canonical_gap_planner() -> None:
    text = source()

    assert "=== 3/4 CURRENT-FLOOR RETAINED HAIR + EYE PHYSICAL PREVIEW ===" in text
    assert "from bodyrig.fidelity_component_gap import build_gap_plan" in text
    assert "Component gap authority targets different current-floor bytes/revision." in text
    assert '($drawable -contains "hair")' in text
    assert '($drawable -contains "eyes")' in text
    assert "Current-floor retained preview lacks physically drawable hair/eyes authority." in text


def test_current_floor_review_recomputes_diagnostic_before_reuse() -> None:
    text = source()

    assert "=== 4/4 DIAGNOSTIC-ONLY V5 SCORE OF CURRENT-FLOOR HAIR + EYE PREVIEW ===" in text
    assert "--allow-incomplete-component-comparison" in text
    assert "--iteration 9001" in text
    assert "$diagnosticAttempt" in text
    assert "Freshly recomputed diagnostic evaluation" in text
    assert "Revalidated existing diagnostic-only evaluation" in text
    assert "Assert-SemanticallyEqualJson -Expected $freshDiagnostic -Actual $existingDiagnostic" in text
    assert "Diagnostic evaluation targets different current-floor package bytes." in text


def test_current_floor_review_summary_reuse_is_exact_semantic_authority() -> None:
    text = source()

    assert "Assert-SemanticallyEqualJson" in text
    assert 'Assert-SemanticallyEqualJson -Expected $summary -Actual $existing' in text
    assert "differs from freshly recomputed authority; refusing stale/tampered reuse." in text
    assert "diagnostic_only = $true" in text
    assert "physical_acceptance_authority = $false" in text
    assert "human_visual_authority_required = $true" in text
    assert "production_activation = $false" in text
