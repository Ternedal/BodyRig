from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoidentity-multiperformer-track-attestation.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_operator_requires_explicit_human_confirmation_and_revision_bound_clean_checkout() -> None:
    text = _text()
    lowered = text.lower()
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmIdentity" in text
    assert "if (-not $ConfirmIdentity.IsPresent)" in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert "git -C $repoRoot status --porcelain" in text
    assert "requires an exact clean BodyRig checkout" in text
    assert "different checkout" in lowered
    assert "--current-revision $head" in text
    assert "--confirm-identity" in text


def test_operator_binds_selected_review_sheet_and_stays_pre_isolation() -> None:
    text = _text()
    lowered = text.lower()
    assert "multiperformer-track-review-candidates.json" in text
    assert "private-track-review\\private-review-index.json" in text
    assert "machine-track-review.json" in text
    assert "TrackCandidateId is not unique" in text
    assert "Selected source-track review sheet" in text
    assert "human_identity_attested" in text
    for field in (
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "target_isolated_source_authority",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation",
    ):
        assert field.lower() in lowered
    assert "next blocker: build and review target-isolated source evidence" in lowered


def test_operator_does_not_run_reconstruction_or_renderer() -> None:
    lowered = _text().lower()
    assert "sith" not in lowered
    assert "unity" not in lowered
    assert "quest" not in lowered
    assert "clone-body" not in lowered
    assert "reconstruction permitted:          false" in lowered
    assert "production activation:             false" in lowered
