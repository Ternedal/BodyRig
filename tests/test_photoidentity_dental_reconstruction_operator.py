from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "run-photoidentity-dental-reconstruction.ps1"


def test_dental_operator_is_clean_checkout_bound_and_fail_closed() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert "git -C $repoRoot status --porcelain" in text
    assert "requires an exact clean BodyRig checkout" in text
    assert "--bodyrig-revision" in text
    assert "$head" in text
    assert "private-fine-identity-review-manifest.json" in text
    assert "photoidentity-fine-identity-attestation.json" in text
    assert "Generic dental fallback: FALSE" in text
    assert "Human review required: TRUE" in text
    assert "Promotion authority: FALSE" in text
    assert "Production activation: FALSE" in text
    assert "bodyrig.photoidentity_dental_reconstruction" in text


def test_dental_operator_has_no_user_supplied_revision_parameter() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    header = text.split(")", 1)[0]
    assert "BodyRigRevision" not in header
