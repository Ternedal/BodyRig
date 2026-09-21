from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bind-photoreal-v2-person.ps1"


def test_photoreal_person_binding_operator_is_checkout_bound() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "Photoreal Person binding requires an exact clean BodyRig checkout." in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert '"--bodyrig-revision", $head' in source


def test_photoreal_person_binding_operator_requires_exact_authority_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--person-library", $PersonLibrary' in source
    assert '"--person-id", $PersonId' in source
    assert '"--assembly-receipt", $AssemblyReceipt' in source
    assert '"--body-release-status", $BodyReleaseStatus' in source
    assert '"--p3-physical-review", $P3PhysicalReview' in source
    assert "output already exists" in source


def test_photoreal_person_binding_operator_cannot_activate_production() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "m4_photoreal_integration_eligible" in source
    assert "production_activation -isnot [bool]" in source
    assert "production_activation -ne $false" in source
    assert "Production activation:      FALSE" in source
