from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "run-source-hair-eye-windows-preview.ps1"


def source() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def test_preview_requires_component_visibility_evidence_before_ready() -> None:
    text = source()

    visibility = text.index('"component-visibility-probe.json"')
    hair = text.index('Assert-PhysicallyDrawableComponent -Visibility $componentVisibility -Label "hair"')
    eyes = text.index('Assert-PhysicallyDrawableComponent -Visibility $componentVisibility -Label "eyes"')
    ready = text.index('BodyRig source hair + eye Windows preview: READY')

    assert visibility < hair < eyes < ready


def test_preview_requires_exact_physical_hair_and_eye_nodes() -> None:
    text = source()

    assert 'NodeName "BodyRigSourceHairReview"' in text
    assert 'NodeName "BodyRigSourceEyeReview"' in text
    for field in (
        "present_in_avatar_bytes",
        "instantiated",
        "active_in_hierarchy",
        "visible_skinned_renderer",
        "visible_renderer_count",
    ):
        assert field in text
    assert "no physically drawable skinned renderer" in text


def test_preview_visibility_probe_is_hash_and_authority_bound() -> None:
    text = source()

    for marker in (
        'bodyrig-component-visibility-probe',
        '[string]$componentVisibility.bodyrig_revision -ne $head',
        '[string]$componentVisibility.platform -ne "windows-unity-univrm"',
        '[string]$componentVisibility.package_sha256 -ne [string]$sourceReview.packageSha256',
        '[string]$componentVisibility.avatar_sha256 -ne (Sha256 $sourceReviewVrm)',
        '$componentVisibility.human_visual_authority_required -ne $true',
        '$componentVisibility.production_activation -ne $false',
        'component-presence-and-runtime-visibility-not-visual-quality-acceptance',
    ):
        assert marker in text


def test_preview_still_does_not_claim_full_fidelity_or_release_authority() -> None:
    text = source()

    assert 'human visual review REQUIRED' in text
    assert 'physical acceptance FALSE' in text
    assert 'production FALSE' in text
    assert 'all_required_present_and_visible -ne $true' not in text
