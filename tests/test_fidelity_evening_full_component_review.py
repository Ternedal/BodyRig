from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening-full-component-review.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_full_component_review_extends_canonical_current_floor_evening_path() -> None:
    text = source()

    assert "run-fidelity-evening-current-floor-review.ps1" in text
    assert "=== 1/3 CURRENT-FLOOR HAIR + EYE REVIEW ===" in text
    assert "Current-floor hair+eye evening review failed" in text
    assert "base_evening_summary_sha256" in text
    assert "Current-floor evening summary crossed its authority boundary." in text


def test_full_component_review_composes_face_secondary_on_exact_retained_hair_eye_runtime() -> None:
    text = source()

    assert "run-face-secondary-hair-eye-windows-preview.ps1" in text
    assert 'Join-Path $hairEyeOutput "runtime"' in text
    assert "HairEyeRuntimeDir = $hairEyeRuntime" in text
    assert "PackagePath = $currentPackage" in text
    assert "source_package_sha256" in text
    assert "face_secondary_drawable" in text
    assert "comparison_package_sha256" in text
    assert "package_promotion_authority" in text


def test_full_component_review_scores_face_secondary_comparison_bytes_not_source_package() -> None:
    text = source()

    assert '"comparison\\face-secondary-hair-eye-comparison.mrbody"' in text
    assert '"windows-preview\\snapshots\\fidelity-render-set.json"' in text
    assert "--iteration 9002" in text
    assert "--allow-incomplete-component-comparison" in text
    assert "Full-component diagnostic candidate SHA-256" in text
    assert "-ne $comparisonPackageSha" in text
    assert "Full-component diagnostic targets different comparison package bytes." in text


def test_full_component_review_persists_gap_state_and_operator_next_actions() -> None:
    text = source()

    assert "component_gap_plan_sha256" in text
    assert "drawable_components = @($drawable)" in text
    assert "missing_components = @($missing)" in text
    assert "next_actions = @($nextActions)" in text
    assert "strict_machine_scoring_ready = [bool]$gap.strict_machine_scoring_ready" in text
    assert "full_fidelity_component_complete = [bool]$gap.strict_machine_scoring_ready" in text
    assert 'Write-Host "Missing:' in text
    assert 'Write-Host "Next:' in text


def test_full_component_review_requires_hair_eyes_and_face_secondary_drawability() -> None:
    text = source()

    assert 'foreach ($required in @("hair", "eyes", "face-secondary"))' in text
    assert "lacks physically drawable $required evidence" in text
    assert "Test-FaceSecondaryComplete" in text
    assert "source_hair_preserved -ne $true" in text
    assert "source_eye_surface_preserved -ne $true" in text


def test_full_component_review_never_starts_expensive_reconstruction_or_claims_release_authority() -> None:
    text = source()

    assert "SiTH reconstruction: NEVER STARTED BY THIS RUNNER" in text
    assert "expensive_reconstruction_rerun = $false" in text
    assert "comparison_only = $true" in text
    assert "diagnostic_only = $true" in text
    assert "physical_acceptance_authority = $false" in text
    assert "human_visual_authority_required = $true" in text
    assert "package_promotion_authority = $false" in text
    assert "production_activation = $false" in text
    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence.ps1",
        '"-m", "bodyrig.sith_reconstruct"',
        "SithSeed",
    ):
        assert forbidden not in text


def test_full_component_review_is_resume_safe_and_opens_only_final_snapshots() -> None:
    text = source()

    assert "Reusing complete face-secondary comparison" in text
    assert "Assert-SemanticallyEqualJson" in text
    assert "Revalidated existing full-component diagnostic evaluation" in text
    assert "Existing full-component evening summary" in text
    assert 'Join-Path $faceSecondaryOutput "windows-preview\\snapshots"' in text
    assert "$baseArgs.OpenSnapshots" not in text
