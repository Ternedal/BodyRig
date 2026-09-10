from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "discover-photoidentity-anatomy-sources.ps1",
    "prepare-photoidentity-anatomy-source-review.ps1",
    "record-photoidentity-anatomy-source-attestation.ps1",
)


def test_anatomy_source_operators_are_exact_checkout_bound() -> None:
    for name in SCRIPTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        lowered = text.lower()
        assert "git -c $reporoot rev-parse head" in lowered
        assert "git -c $reporoot status --porcelain" in lowered
        assert "bodyrig.__file__" in text
        assert "different checkout" in lowered
        assert "powershell 7+" in lowered


def test_anatomy_source_operators_do_not_invoke_avatar_render_or_reconstruction() -> None:
    forbidden = (
        "run-reference-windows-renderer-probe",
        "run-fidelity-windows-render-probe",
        "run-windows-renderer-probe",
        "sith_reconstruct",
        "clone-body-from-stash",
        "build-subject-anatomy-candidate",
        "promote-high-fidelity-anatomy",
        "unity.exe",
    )
    for name in SCRIPTS:
        lowered = (ROOT / name).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in lowered


def test_human_attestation_requires_all_three_explicit_source_confirmations() -> None:
    text = (ROOT / "record-photoidentity-anatomy-source-attestation.ps1").read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmRearView" in text
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmTorsoChestAnatomyVisible" in text
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmWaistHipsAnatomyVisible" in text
    assert '"--confirm-rear-view"' in text
    assert '"--confirm-torso-chest-anatomy-visible"' in text
    assert '"--confirm-waist-hips-anatomy-visible"' in text
    assert "actual visible anatomy only" in text.lower()


def test_machine_discovery_never_grants_semantic_anatomy_authority() -> None:
    source = (ROOT / "bodyrig" / "photoidentity_anatomy_source_discovery.py").read_text(encoding="utf-8")
    assert '"machine_anatomy_identity_authority": False' in source
    assert '"machine_rear_orientation_authority": False' in source
    assert '"machine_asserts_anatomy_visible": False' in source
    assert '"machine_asserts_rear_orientation": False' in source
    assert '"production_activation": False' in source


def test_human_attestation_adapter_is_source_observability_only() -> None:
    source = (ROOT / "bodyrig" / "photoidentity_anatomy_source_attestation.py").read_text(encoding="utf-8")
    assert 'ADAPTER = "human-source-anatomy-observability-attestation"' in source
    assert 'DOMAIN_MIN_SCENES = {"body_rear": 1, "torso_chest": 2, "waist_hips": 2}' in source
    assert '"generic_guessing_permitted": False' in source
    assert '"production_activation": False' in source
