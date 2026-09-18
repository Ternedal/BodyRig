from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "diagnose-photoreal-v2-calibration.ps1"


def test_operator_script_uses_run_root_diagnostic_cli() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Set-StrictMode -Version Latest' in text
    assert '$ErrorActionPreference = "Stop"' in text
    assert (
        '"bodyrig.photoreal_identity_calibration_diagnostic_cli"'
        in text
    )
    assert '"--run-root"' in text
    assert '"--top-matches"' in text
    assert 'Authority: diagnostic-only' in text
    assert '$jsonText = (& $python @arguments | Out-String).Trim()' in text
    assert '$result = $jsonText | ConvertFrom-Json' in text
    assert 'Stage-13 diagnostic summary' in text
    assert 'Separation margin: observed' in text
    assert 'Highest negative match' in text
    assert 'Source: $($highest.resolved_path)' in text
    assert 'Timestamp seconds: $($highest.timestamp_seconds)' in text
    assert 'Authority: diagnostic-only; no matching, training, or production authority.' in text
    assert 'exit $exitCode' in text
    assert 'exit 0' in text


def test_operator_script_requires_existing_calibration_artifacts() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"identity-bank.json"' in text
    assert '"identity-calibration-plan.json"' in text
    assert (
        '"identity-calibration-extractor\\output\\'
        'negative-observations.json"'
    ) in text


def test_operator_script_keeps_output_override_optional() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '[string]$Out = ""' in text
    assert 'if (-not [string]::IsNullOrWhiteSpace($Out))' in text
    assert '$arguments += @("--out", $outputPath)' in text
