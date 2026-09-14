from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening-review.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_review_selects_best_v5_candidate_before_physical_preview() -> None:
    text = source()

    assert "run-fidelity-v5-review.ps1" in text
    assert "$best = [int]$decision.best_iteration" in text
    assert "$best -notin @(1,2,3)" in text
    assert '"iteration-01-baseline.json"' in text
    assert '"iteration-02-refit1.json"' in text
    assert '"iteration-03-reconstruction2.json"' in text
    assert "Selected package bytes differ from the candidate bytes scored by V5." in text
    assert "measurement.candidate_sha256" in text


def test_evening_review_resolves_retained_reconstruction_without_rerun() -> None:
    text = source()

    assert "Resolve-WorkspaceByReconstructionHash" in text
    assert '"sith-input-v1\\reconstruction.json"' in text
    assert '"identity-workspace.txt"' in text
    assert "reconstruction_authority_sha256" in text
    assert "Expected exactly one retained identity workspace" in text
    assert "SiTH reconstruction: NEVER STARTED BY THIS RUNNER" in text

    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence.ps1",
        "sith_reconstruct",
        "SithSeed",
    ):
        assert forbidden not in text


def test_evening_review_requires_physical_hair_and_eye_drawability() -> None:
    text = source()

    assert "run-retained-hair-eye-preview.ps1" in text
    assert '"windows-preview\\component-visibility-probe.json"' in text
    assert 'foreach ($label in @("hair","eyes"))' in text
    assert ".present_in_avatar_bytes -ne $true" in text
    assert ".instantiated -ne $true" in text
    assert ".active_in_hierarchy -ne $true" in text
    assert ".visible_skinned_renderer -ne $true" in text
    assert ".visible_renderer_count -lt 1" in text
    assert "Retained preview completed without physically drawable $label evidence." in text


def test_evening_review_scores_new_preview_as_diagnostic_only() -> None:
    text = source()

    assert "DIAGNOSTIC-ONLY V5 SCORE OF HAIR + EYE PREVIEW" in text
    assert "--allow-incomplete-component-comparison" in text
    assert "--iteration 9001" in text
    assert "diagnostic_only = $true" in text
    assert "full_fidelity_component_complete = $false" in text
    assert "human_visual_authority_required = $true" in text
    assert "production_activation = $false" in text
    assert 'semantics = "retained-hair-eye-physical-preview-plus-diagnostic-score-not-full-fidelity-acceptance"' in text


def test_evening_review_is_resume_aware_without_overwriting_authority() -> None:
    text = source()

    assert "Test-RetainedPreviewComplete" in text
    assert "Reusing complete retained preview" in text
    assert "Retained preview output exists but is incomplete; refusing to overwrite evidence" in text
    assert "Reusing diagnostic-only evaluation" in text
    assert "Existing evening review summary targets different authority bytes; refusing overwrite." in text
    assert "Assert-HeadPinned" in text
    assert "requires an exact clean BodyRig checkout" in text


def test_evening_review_surfaces_human_visual_qa_paths() -> None:
    text = source()

    for snapshot in (
        "front-full.png",
        "face-front.png",
        "eyes-closeup.png",
    ):
        assert snapshot in text
    assert "BODYRIG EVENING REVIEW READY FOR HUMAN VISUAL QA" in text
    assert "Snapshots:" in text
    assert "OpenSnapshots" in text
