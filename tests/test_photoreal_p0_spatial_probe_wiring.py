from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run-photoreal-p0-windows.ps1"


def test_p0_runs_spatial_metadata_probe_between_byte_verification_and_scan_plan() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    source_verify = script.index("bodyrig.photoreal_source_verify_cli")
    spatial_probe = script.index("bodyrig.photoreal_spatial_metadata_probe_cli")
    scan_plan = script.index("bodyrig.photoreal_scan_plan_cli")

    assert source_verify < spatial_probe < scan_plan

    probe_block = script[spatial_probe:scan_plan]
    assert "--inventory" in probe_block
    assert "$InventoryPath" in probe_block
    assert "--receipt" in probe_block
    assert "$ReceiptPath" in probe_block
    assert "--out" in probe_block
    assert "$SpatialMetadataProbePath" in probe_block


def test_p0_keeps_diagnostic_probe_out_of_scan_plan_authority() -> None:
    script = RUNNER.read_text(encoding="utf-8")

    scan_plan = script.index("bodyrig.photoreal_scan_plan_cli")
    next_stage = script.index('5/16 TRAIN-ONLY IDENTITY BOOTSTRAP', scan_plan)
    scan_block = script[scan_plan:next_stage]

    assert "$SpatialMetadataProbePath" not in scan_block
    assert '3B/16 SPATIAL METADATA PROBE (DIAGNOSTIC ONLY)' in script
    assert "spatial_metadata_probe = $script:SpatialMetadataProbePath" in script
