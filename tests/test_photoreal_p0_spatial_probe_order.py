from __future__ import annotations

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run-photoreal-p0-windows.ps1"


def test_spatial_metadata_probe_runs_after_receipt_and_before_scan_plan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    receipt_stage = source.index('Invoke-PythonStage -Label "3/16 BYTE-VERIFY COMPLETE SOURCE UNIVERSE"')
    probe_stage = source.index('Invoke-PythonStage -Label "3B/16 SPATIAL METADATA PROBE (DIAGNOSTIC ONLY)"')
    scan_stage = source.index('Invoke-PythonStage -Label "4/16 DETERMINISTIC SCOUT PLAN"')

    assert receipt_stage < probe_stage < scan_stage
    assert '"-m", "bodyrig.photoreal_spatial_metadata_probe_cli"' in source
    assert '"--inventory", $InventoryPath' in source[probe_stage:scan_stage]
    assert '"--receipt", $ReceiptPath' in source[probe_stage:scan_stage]
    assert '"--out", $SpatialMetadataProbePath' in source[probe_stage:scan_stage]


def test_diagnostic_probe_is_not_projection_authority_input() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    probe_stage = source.index('Invoke-PythonStage -Label "3B/16 SPATIAL METADATA PROBE (DIAGNOSTIC ONLY)"')
    scan_stage = source.index('Invoke-PythonStage -Label "4/16 DETERMINISTIC SCOUT PLAN"')
    next_stage = source.index('Invoke-PythonStage -Label "5/16 TRAIN-ONLY IDENTITY BOOTSTRAP"')
    scan_block = source[scan_stage:next_stage]

    assert probe_stage < scan_stage
    assert "$SpatialMetadataProbePath" not in scan_block
    assert "--projection-authority" not in scan_block
    assert '"--plan", $PlanPath' in scan_block
    assert '"--receipt", $ReceiptPath' in scan_block
    assert '"--out", $ScanPlanPath' in scan_block
