from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "probe-photoreal-scout-authority.ps1").read_text(encoding="utf-8")


def test_scout_authority_replay_is_clean_checkout_and_read_only() -> None:
    assert 'git -C $repoRoot status --porcelain' in SCRIPT
    assert 'Scout authority replay requires an exact clean BodyRig checkout.' in SCRIPT
    assert 'source-inventory.json' in SCRIPT
    assert 'dataset-plan.json' in SCRIPT
    assert 'source-receipt.json' in SCRIPT
    assert 'ProbeRoot must remain outside the original P0 output root.' in SCRIPT
    assert 'ProbeRoot must be a new non-existing directory' in SCRIPT
    assert 'Original mutation: FALSE' in SCRIPT
    assert 'diagnostic-spatial-container-probe.json' in SCRIPT
    assert 'diagnostic-scan-plan.json' in SCRIPT


def test_scout_authority_replay_uses_current_metadata_and_scan_plan_code() -> None:
    assert 'bodyrig.photoreal_spatial_metadata_probe_cli' in SCRIPT
    assert 'bodyrig.photoreal_scan_plan_cli' in SCRIPT
    assert 'Exact equi:' in SCRIPT
    assert 'Exact mesh (mshp):' in SCRIPT
    assert 'Exact cubemap (cbmp):' in SCRIPT
    assert 'Stereo custom:' in SCRIPT
    assert 'Mesh+custom cand.:' in SCRIPT
    assert 'Stereo right-left:' in SCRIPT
    assert 'Stereo reserved:' in SCRIPT
    assert 'Mesh-custom in scout:' in SCRIPT
    assert 'CURRENT STAGE-4 AUTHORITY GATE: PASS (DIAGNOSTIC REPLAY ONLY)' in SCRIPT
    assert 'CURRENT STAGE-4 AUTHORITY GATE: BLOCKED' in SCRIPT


def test_scout_authority_replay_never_grants_downstream_authority() -> None:
    assert 'Test-StrictBoolean -Value $Probe.deprojection_authority -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $Probe.photoreal_acceptance_authority -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $Probe.production_activation -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $Scan.teacher_training_authorized -Expected $false' in SCRIPT
    assert 'Test-StrictBoolean -Value $Scan.production_activation -Expected $false' in SCRIPT
    assert 'Spatial bootstrap:    FALSE' in SCRIPT
    assert 'Do not reuse this diagnostic scout plan as canonical P0 authority.' in SCRIPT
    assert 'teacher_training_authorized = $true' not in SCRIPT
    assert 'production_activation = $true' not in SCRIPT
