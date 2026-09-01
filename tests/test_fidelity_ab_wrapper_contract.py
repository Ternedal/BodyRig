from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fidelity_ab_wrapper_is_strict_and_checkout_bound() -> None:
    text = (ROOT / "compare-fidelity-ab.ps1").read_text(encoding="utf-8")
    assert "bodyrig.fidelity_ab" in text
    assert "bodyrig.fidelity_ab_cli" in text
    assert "--require-clean-appearance-ab" in text
    assert "--out" in text
    assert "StartsWith($repoRoot" in text
    assert "production activation" in text.lower()
