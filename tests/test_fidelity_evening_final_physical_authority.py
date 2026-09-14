from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT = (ROOT / "run-fidelity-evening-current-floor-review.ps1").read_text(encoding="utf-8")
TOP = (ROOT / "run-fidelity-evening.ps1").read_text(encoding="utf-8")


def test_summary_exposes_source_and_final_physical_authority() -> None:
    for token in (
        "source_current_floor_package_sha256 = $currentPackageSha",
        "physical_authority_kind = $physicalAuthorityKind",
        "physical_component_package_sha256 = $physicalAuthorityPackageSha",
        "physical_comparison_package_sha256 = $physicalComparisonPackageSha",
        "physical_component_visibility_probe_sha256 = Sha256 $visibilityPath",
        "physical_render_set_sha256 = Sha256 $renderSet",
    ):
        assert token in CURRENT
    assert '$physicalAuthorityKind = "retained-hair-eye"' in CURRENT
    assert '$physicalAuthorityKind = "face-secondary-hair-eye-comparison"' in CURRENT


def test_top_level_rehashes_final_physical_bytes_before_gap_recompute() -> None:
    visibility_guard = TOP.index("Final physical visibility-probe bytes differ from current-floor summary authority.")
    render_guard = TOP.index("Final physical render-set bytes differ from current-floor summary authority.")
    recompute = TOP.index("--visibility-probe $visibility", render_guard)
    assert visibility_guard < render_guard < recompute
    assert "physical_component_visibility_probe_sha256" in TOP
    assert "physical_render_set_sha256" in TOP
    assert "component_visibility_probe_sha256" in TOP
    assert "component_gap_render_set_sha256" in TOP


def test_source_and_comparison_package_authorities_remain_distinct() -> None:
    assert "source_current_floor_package_sha256" in TOP
    assert "physical_component_package_sha256" in TOP
    assert "physical_comparison_package_sha256" in TOP
    assert "Current-floor source package summary authority disagrees" in TOP
    assert "Retained physical authority points at different source package bytes." in TOP
    assert "Current-floor summary points at a different physical comparison package." in TOP


def test_existing_gap_advances_only_from_fresh_retained_predecessor() -> None:
    for token in (
        "Fresh retained predecessor component gap plan",
        "Existing retained predecessor component gap plan",
        "component-gap-plan.retained-hair-eye.json",
        "Archived retained predecessor component gap plan",
        "Advanced persisted component gap from exact retained predecessor",
    ):
        assert token in TOP
    predecessor = TOP.index("--visibility-probe $retainedVisibility")
    compare = TOP.index("Assert-SemanticallyEqualJson -Expected $freshRetainedGap -Actual $existingGap", predecessor)
    replace = TOP.index("Move-Item -LiteralPath $gapAttempt -Destination $gapPath", compare)
    assert predecessor < compare < replace


def test_diagnostic_source_lineage_and_safety_boundaries_are_unchanged() -> None:
    assert "--render-set $diagnosticRenderSet" in CURRENT
    assert "Diagnostic evaluation targets different current-floor package bytes." in CURRENT
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
