from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_top_level_evening_command_runs_retained_review_then_gap_planner() -> None:
    text = source()

    assert "run-fidelity-evening-review.ps1" in text
    assert "bodyrig.fidelity_component_gap" in text
    assert "--visibility-probe" in text
    assert "--render-set" in text
    assert "component-gap-plan.json" in text
    assert "BODYRIG EVENING REVIEW - QUALIFIED NEXT STEP" in text


def test_top_level_evening_command_preserves_resume_and_authority_boundaries() -> None:
    text = source()

    assert "Reusing component gap plan" in text
    assert "Component gap plan targets different revision/package authority" in text
    assert "Component gap plan crossed the comparison-only authority boundary" in text
    assert "$gap.production_activation -ne $false" in text
    assert "$gap.human_visual_authority_required -ne $true" in text
    assert "Human visual QA:    REQUIRED" in text
    assert "Production:         FALSE" in text


def test_top_level_evening_command_does_not_start_reconstruction_or_clone() -> None:
    text = source()

    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence",
        "sith_reconstruct",
        "SithSeed",
    ):
        assert forbidden not in text


def test_top_level_evening_command_forwards_optional_runtime_inputs_without_forcing_them() -> None:
    text = source()

    for name in (
        "Rebuild1IdentityWorkspace",
        "Rebuild2IdentityWorkspace",
        "IdentityRoot",
        "UnityExe",
        "SkipBuild",
    ):
        assert name in text
    assert "OpenSnapshots" in text
    assert "Start-Process explorer.exe" in text


def test_top_level_evening_command_prints_drawable_missing_and_next_actions() -> None:
    text = source()

    assert "Drawable:" in text
    assert "Missing:" in text
    assert "Strict scoring:" in text
    assert "Next actions:" in text
    assert "foreach ($action in $actions)" in text
    assert "$action.id" in text
    assert "$action.reason" in text
