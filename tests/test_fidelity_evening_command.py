from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_command_delegates_to_canonical_current_floor_review() -> None:
    text = source()

    assert "run-fidelity-evening-current-floor-review.ps1" in text
    assert "Current-floor evening review failed" in text
    assert "current_floor_refit_repackage" in text
    assert "expensive_reconstruction_rerun" in text
    assert "physical_acceptance_authority" in text
    assert "human_visual_authority_required" in text
    assert "production_activation" in text


def test_evening_command_recomputes_exact_component_gap_before_reuse() -> None:
    text = source()

    assert "bodyrig.fidelity_component_gap" in text
    assert "--visibility-probe $visibility" in text
    assert "--render-set $renderSet" in text
    assert "$gapAttempt" in text
    assert "Fresh current-floor component gap plan" in text
    assert "Revalidated existing component gap plan" in text
    assert "Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap" in text
    assert "differs from freshly recomputed authority; refusing stale/tampered reuse" in text


def test_evening_command_binds_gap_to_current_floor_package_and_revision() -> None:
    text = source()

    assert '[string]$gap.bodyrig_revision -ne $head' in text
    assert '[string]$gap.package_sha256 -ne [string]$summary.current_floor_package_sha256' in text
    assert "$gap.human_visual_authority_required -ne $true" in text
    assert "$gap.production_activation -ne $false" in text


def test_evening_command_prints_qualified_operator_result() -> None:
    text = source()

    assert "BODYRIG EVENING RESULT" in text
    assert "Drawable:" in text
    assert "Missing:" in text
    assert "Strict scoring:" in text
    assert "Qualified next actions:" in text
    assert "foreach ($action in $actions)" in text
    assert "$action.id" in text
    assert "$action.reason" in text
    assert "Human visual QA: REQUIRED" in text
    assert "Production:      FALSE" in text
    assert "Snapshots:" in text
    assert "Start-Process explorer.exe" in text


def test_evening_command_does_not_introduce_clone_or_reconstruction_paths() -> None:
    text = source()

    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence",
        '"-m", "bodyrig.sith_reconstruct"',
        "reconstruct_sith(",
        "SithSeed",
    ):
        assert forbidden not in text
