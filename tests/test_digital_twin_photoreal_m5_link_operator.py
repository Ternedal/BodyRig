from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "link-photoreal-v2-m5.ps1"


def test_photoreal_m5_link_operator_is_exact_checkout_bound() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "Photoreal M5 link requires an exact clean BodyRig checkout." in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert '"--bodyrig-revision", $head' in source


def test_photoreal_m5_link_operator_requires_existing_m4_and_acceptance() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--composition-authority-dir", $CompositionAuthorityDir' in source
    assert '"--acceptance-dir", $AcceptanceDir' in source
    assert '"--m4-photoreal-link-dir", $M4PhotorealLinkDir' in source


def test_photoreal_m5_link_operator_stays_non_activating() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "M6 Photoreal integration:   ELIGIBLE" in source
    assert "Production activation:      FALSE" in source
