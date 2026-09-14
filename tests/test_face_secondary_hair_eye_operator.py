from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-face-secondary-hair-eye-windows-preview.ps1"
COMPOSER = ROOT / "bodyrig" / "face_secondary_hair_eye_review.py"
COMPARISON = ROOT / "bodyrig" / "face_secondary_hair_eye_comparison.py"


def test_operator_composes_materializes_and_physically_probes_without_promotion() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "bodyrig.face_secondary_hair_eye_review" in text
    assert "bodyrig.face_secondary_hair_eye_comparison" in text
    assert "run-fidelity-windows-render-probe.ps1" in text
    assert "bodyrig.fidelity_component_gap" in text
    assert 'foreach ($required in @("hair", "eyes", "face-secondary"))' in text
    assert "face_secondary_drawable = $true" in text
    assert "physical_acceptance_authority = $false" in text
    assert "package_promotion_authority = $false" in text
    assert "production_activation = $false" in text


def test_operator_never_invokes_promotion_clone_or_reconstruction() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "promote-high-fidelity-face-secondary",
        "high_fidelity_face_secondary_promotion",
        "clone-body-from-stash",
        '"-m", "bodyrig.sith_reconstruct"',
        "reconstruct_sith(",
        "SithSeed",
    ):
        assert forbidden not in text


def test_composer_uses_separate_review_authority_and_preserves_hair_eye_boundaries() -> None:
    text = COMPOSER.read_text(encoding="utf-8")

    assert 'FORMAT = "bodyrig-face-secondary-on-hair-eye-review-runtime"' in text
    assert 'SOURCE_FORMAT = "bodyrig-source-hair-eye-review-runtime"' in text
    assert 'EMBEDDED_KEY = "faceSecondaryHairEyeReviewRuntime"' in text
    assert '"sourceHairPreserved": True' in text
    assert '"sourceEyeSurfacePreserved": True' in text
    assert '"faceSecondaryComponentAuthority": False' in text
    assert '"packageMutationPerformed": False' in text
    assert '"productionActivation": False' in text
    assert "eyePromotion" not in text


def test_comparison_package_is_explicitly_non_promoting() -> None:
    text = COMPARISON.read_text(encoding="utf-8")

    assert 'FORMAT = "bodyrig-face-secondary-hair-eye-comparison"' in text
    assert '"comparisonOnly": True' in text
    assert '"physicalAcceptanceAuthority": False' in text
    assert '"humanReviewRequired": True' in text
    assert '"packagePromotionAuthority": False' in text
    assert '"productionActivation": False' in text
    assert "_write_package(package, comparison, avatar_vrm=review_vrm)" in text
