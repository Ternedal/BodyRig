from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "run-photoreal-p0-windows.ps1").read_text(encoding="utf-8")


def test_default_p0_derives_source_path_map_after_exhaustive_inventory() -> None:
    inventory = RUNNER.index('=== 1/16 EXHAUSTIVE STASH INVENTORY ===')
    source_map = RUNNER.index('1B/16 PROVE EXACT SOURCE PATH MAP')
    dataset_plan = RUNNER.index('2/16 LEAKAGE-SAFE DATASET PLAN')
    byte_verify = RUNNER.index('3/16 BYTE-VERIFY COMPLETE SOURCE UNIVERSE')

    assert inventory < source_map < dataset_plan < byte_verify
    assert '"-m", "bodyrig.photoreal_inventory_path_map_cli"' in RUNNER
    assert '"--inventory", $InventoryPath' in RUNNER
    assert '"--out", $GeneratedSourcePathMap' in RUNNER
    assert '"--path-map", $PathMap' in RUNNER


def test_negative_inventory_gets_union_calibration_path_map_before_byte_verify() -> None:
    negatives = RUNNER.index('9/16 DISCOVER SOURCE-AUTHORITATIVE NEGATIVES')
    calibration_map = RUNNER.index('9B/16 PROVE EXACT CALIBRATION PATH MAP')
    negative_verify = RUNNER.index('10/16 BYTE-VERIFY NEGATIVE CALIBRATION SOURCES')

    assert negatives < calibration_map < negative_verify
    assert '"--negative-inventory", $NegativeInventoryPath' in RUNNER
    assert '"--out", $GeneratedCalibrationPathMap' in RUNNER
    assert '"--path-map", $CalibrationPathMap' in RUNNER


def test_explicit_path_map_remains_supported_and_bypasses_generation() -> None:
    assert '$PathMapWasExplicit = -not [string]::IsNullOrWhiteSpace($PathMap)' in RUNNER
    assert '$PathMap = Need-File -Path $PathMap -Label "Explicit Stash path map"' in RUNNER
    assert RUNNER.count('if (-not $PathMapWasExplicit) {') == 2
    assert '$CalibrationPathMap = $PathMap' in RUNNER


def test_p0_no_longer_calls_sample_based_generic_path_map_discovery() -> None:
    assert 'configure-stash-path-map.ps1' not in RUNNER
    assert 'Get-PerformerPathMapCandidate' not in RUNNER
