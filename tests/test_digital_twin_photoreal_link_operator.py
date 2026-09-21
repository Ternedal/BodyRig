from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "link-photoreal-v2-m4.ps1"


def test_m4_photoreal_link_operator_is_exact_checkout_bound() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "M4 Photoreal link requires an exact clean BodyRig checkout." in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert '"--bodyrig-revision", $head' in source


def test_m4_photoreal_link_operator_requires_exact_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--composition-authority-dir", $CompositionAuthorityDir' in source
    assert '"--photoreal-person-binding", $PhotorealPersonBinding' in source
    assert '"--p3-physical-review", $P3PhysicalReview' in source
    assert '$arguments += @("--library-root", $LibraryRoot)' in source


def test_m4_photoreal_link_operator_stays_non_activating() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "M5 Photoreal integration:    ELIGIBLE" in source
    assert "Production activation:       FALSE" in source
