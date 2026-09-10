from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_status_router_is_exact_checkout_bound_and_never_starts_avatar_work() -> None:
    source = (ROOT / "photoidentity-source-status.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "git -c $reporoot rev-parse head" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
    assert "bodyrig.photoidentity_source_status" in source
    assert "generic guess:  false" in lowered
    assert "production:     false" in lowered
    assert "record_complete_nail_attestation_after_source_review" not in lowered  # Python action, not shell execution.
    assert "manager.start" not in lowered
    for forbidden in (
        "run-reference-windows-renderer",
        "run-fidelity-windows-render",
        "sith_reconstruct",
        "unity.exe",
    ):
        assert forbidden not in lowered


def test_router_requires_human_source_review_instead_of_synthesizing_attestation() -> None:
    source = (ROOT / "photoidentity-source-status.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert '"nail-human-review"' in source
    assert '"anatomy-human-review"' in source
    assert "do not record attestation unless both nail domains are genuinely visible" in lowered
    assert "no hidden anatomy may be inferred through clothing or occlusion" in lowered
    assert "-confirmfingernails" not in lowered
    assert "-confirmrearview" not in lowered


def test_registration_operator_binds_final_anatomy_bundle_and_does_not_render() -> None:
    source = (ROOT / "register-photoidentity-source-authority.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "git -c $reporoot rev-parse head" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
    assert "anatomy-attested-evidence" in lowered
    assert "bodyrig.photoidentity_registry_cli register" in source
    assert "refusing cross-revision registration" in lowered
    assert "generic guessing false" in lowered
    assert "production activation false" in lowered
    for forbidden in (
        "manager.start",
        "run-reference-windows-renderer",
        "run-fidelity-windows-render",
        "sith_reconstruct",
        "unity.exe",
    ):
        assert forbidden not in lowered
