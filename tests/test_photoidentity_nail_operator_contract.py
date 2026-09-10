from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_discovery_operator_is_exact_checkout_bound_and_source_only() -> None:
    source = (ROOT / "discover-photoidentity-nail-sources.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "git -c $reporoot rev-parse head" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
    assert "bodyrig.sith_preflight" in source
    assert "bodyrig.photoidentity_nail_source_discovery" in source
    assert "source closeups only" in lowered
    assert "machine nail authority false" in lowered
    for forbidden in ("unity", "run-reference-windows-renderer", "run-fidelity-windows-render", "sith_reconstruct"):
        assert forbidden not in lowered


def test_review_operator_opens_only_private_source_closeups() -> None:
    source = (ROOT / "prepare-photoidentity-nail-source-review.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "bodyrig.photoidentity_nail_review_prepare" in source
    assert "private-nail-source-review" in lowered
    assert "no avatar render was created" in lowered
    assert "start-process explorer.exe" in lowered
    assert "unity" not in lowered
    assert "renderer" not in lowered


def test_attestation_operator_requires_explicit_human_confirmation_and_note() -> None:
    source = (ROOT / "record-photoidentity-nail-source-attestation.ps1").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "[switch]$ConfirmFingernails" in source
    assert "[switch]$ConfirmToenails" in source
    assert "[Parameter(Mandatory = $true)][string]$QualityNote" in source
    assert "if (-not $confirmfingernails -and -not $confirmtoenails)" in lowered
    assert "bodyrig.photoidentity_nail_source_attestation" in source
    assert "cross-revision human authority" in lowered
    assert "no avatar render" in lowered
    assert "generic guessing" in lowered
    for forbidden in ("unity", "run-reference-windows-renderer", "run-fidelity-windows-render", "sith_reconstruct"):
        assert forbidden not in lowered
