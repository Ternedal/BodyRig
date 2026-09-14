from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT = (ROOT / "run-fidelity-evening-current-floor-review.ps1").read_text(encoding="utf-8")
TOP = (ROOT / "run-fidelity-evening.ps1").read_text(encoding="utf-8")


def test_current_floor_automatically_advances_missing_face_secondary() -> None:
    assert "run-face-secondary-hair-eye-windows-preview.ps1" in CURRENT
    assert 'if (-not ($drawable -contains "face-secondary"))' in CURRENT
    assert "PackagePath = $currentPackage" in CURRENT
    assert "HairEyeRuntimeDir = $hairEyeRuntimeDir" in CURRENT
    assert "Face-secondary hair+eye preview failed" in CURRENT
    assert "Face-secondary continuation lacks physically drawable $required authority." in CURRENT


def test_face_secondary_reuse_is_exact_hash_bound_and_review_only() -> None:
    for token in (
        "ExpectedSourcePackageSha",
        "ExpectedHairEyeReceiptSha",
        "ExpectedHairEyeVrmSha",
        "face_secondary_runtime_receipt_sha256",
        "comparison_receipt_sha256",
        "comparison_package_sha256",
        "component_visibility_probe_sha256",
        "render_set_sha256",
        "gap_plan_sha256",
        "$summary.physical_acceptance_authority -ne $false",
        "$summary.human_visual_authority_required -ne $true",
        "$summary.package_promotion_authority -ne $false",
        "$summary.production_activation -ne $false",
    ):
        assert token in CURRENT


def test_diagnostic_score_stays_on_source_package_and_retained_render_set() -> None:
    diagnostic = CURRENT.index("=== 4/4 DIAGNOSTIC-ONLY V5 SCORE")
    render = CURRENT.index("--render-set $retainedRenderSet", diagnostic)
    package_check = CURRENT.index("Diagnostic evaluation targets different current-floor package bytes.", render)
    assert render < package_check
    assert "--render-set $physicalRenderSet" not in CURRENT
    assert "physical_comparison_package_sha256 = $physicalComparisonPackageSha" in CURRENT
    assert "source_current_floor_package_sha256 = $currentPackageSha" in CURRENT


def test_summary_component_state_uses_final_physical_authority() -> None:
    assert "physical_authority_kind = $physicalAuthorityKind" in CURRENT
    assert "physical_component_package_sha256 = $physicalPackageSha" in CURRENT
    assert "physical_component_visibility_probe_sha256 = Sha256 $physicalVisibilityPath" in CURRENT
    assert "physical_render_set_sha256 = Sha256 $physicalRenderSet" in CURRENT
    assert 'hair = $physicalDrawable -contains "hair"' in CURRENT
    assert 'face_secondary = $physicalDrawable -contains "face-secondary"' in CURRENT
    assert "full_fidelity_component_complete = [bool]$physicalVisibility.all_required_present_and_visible" in CURRENT


def test_top_level_recomputes_gap_from_final_physical_authority() -> None:
    assert '"face-secondary-hair-eye-comparison"' in TOP
    assert "face-secondary-hair-eye-$selected" in TOP
    assert "physical_component_package_sha256" in TOP
    assert "physical_component_visibility_probe_sha256" in TOP
    assert "physical_render_set_sha256" in TOP
    assert "--visibility-probe $visibility" in TOP
    assert "--render-set $renderSet" in TOP
    assert '[string]$gap.package_sha256 -ne $physicalPackageSha' in TOP
    assert 'Join-Path $physicalRoot "windows-preview\\snapshots"' in TOP


def test_top_level_only_advances_a_proven_exact_retained_predecessor_gap() -> None:
    assert "Fresh retained predecessor component gap plan" in TOP
    assert "Existing retained predecessor component gap plan" in TOP
    assert "component-gap-plan.retained-hair-eye.json" in TOP
    assert "Advanced persisted component gap from exact retained predecessor" in TOP


def test_evening_continuation_keeps_hfn_human_and_release_boundaries() -> None:
    assert "physical_acceptance_authority = $false" in CURRENT
    assert "human_visual_authority_required = $true" in CURRENT
    assert "production_activation = $false" in CURRENT
    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence",
        '"-m", "bodyrig.sith_reconstruct"',
        "reconstruct_sith(",
        "promote-high-fidelity-face-secondary",
    ):
        assert forbidden not in CURRENT
