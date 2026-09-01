from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_review_bundle_wrapper_is_checkout_bound_and_create_only() -> None:
    text = (ROOT / "build-fidelity-review-bundle.ps1").read_text(encoding="utf-8")
    assert "[string]$BodyRigPython" in text
    assert "bodyrig.fidelity_review_bundle" in text
    assert "$env:PYTHONPATH" in text
    assert "PathSeparator" in text
    assert "StartsWith($repoRoot" in text
    assert "Review bundle output already exists" in text
    assert "--historical-render" in text
    assert "--pr40-render" in text
    assert "--pr41-render" in text
    assert "--ab-evidence" in text
    assert "human visual authority remains mandatory" in text.lower()
    assert "cannot grant production activation" in text.lower()
