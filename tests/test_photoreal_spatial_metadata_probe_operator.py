from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "probe-photoreal-spatial-metadata.ps1").read_text(encoding="utf-8")


def test_spatial_probe_operator_is_clean_checkout_and_diagnostic_only() -> None:
    assert 'git -C $repoRoot status --porcelain' in SCRIPT
    assert 'Spatial metadata probe requires an exact clean BodyRig checkout.' in SCRIPT
    assert 'bodyrig.photoreal_spatial_metadata_probe_cli' in SCRIPT
    assert 'source-inventory.json' in SCRIPT
    assert 'source-receipt.json' in SCRIPT
    assert 'spatial-container-probe.json' in SCRIPT
    assert 'Diagnostic only:   TRUE' in SCRIPT
    assert 'Deprojection auth: FALSE' in SCRIPT
    assert 'Photoreal accept:  FALSE' in SCRIPT
    assert 'Production:        FALSE' in SCRIPT


def test_spatial_probe_operator_rejects_authority_crossing() -> None:
    assert 'Test-StrictBoolean -Value $probe.diagnostic_only -Expected $true' in SCRIPT
    assert 'Test-StrictBoolean -Value $probe.deprojection_authority -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $probe.photoreal_acceptance_authority -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $probe.build_only -Expected $true' in SCRIPT
    assert 'Test-StrictBoolean -Value $probe.runtime_dependency -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $probe.production_activation -Expected $false' in SCRIPT
    assert 'crossed its diagnostic-only authority boundary' in SCRIPT
    assert 'teacher_training_authorized = $true' not in SCRIPT
    assert 'production_activation = $true' not in SCRIPT
