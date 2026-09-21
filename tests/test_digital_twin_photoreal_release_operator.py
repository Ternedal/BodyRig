from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "finalize-photoreal-digital-twin.ps1"


def test_photoreal_m6_operator_is_exact_checkout_bound() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "Photoreal M6 release requires an exact clean BodyRig checkout." in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert '"--bodyrig-revision", $head' in source


def test_photoreal_m6_operator_requires_both_release_chains() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--canonical-m6-release-dir", $CanonicalM6ReleaseDir' in source
    assert '"--photoreal-m5-link-dir", $PhotorealM5LinkDir' in source
    assert '"--m4-photoreal-link-dir", $M4PhotorealLinkDir' in source
    assert '"--composition-authority-dir", $CompositionAuthorityDir' in source
    assert '"--acceptance-dir", $AcceptanceDir' in source


def test_photoreal_m6_operator_activates_only_at_final_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Photoreal ready:      REQUIRES STRICT READBACK" in source
    assert "Production:           FINAL GATE ONLY" in source
    assert "Photoreal digital twin:     READY" in source
    assert "Production activation:      TRUE" in source
