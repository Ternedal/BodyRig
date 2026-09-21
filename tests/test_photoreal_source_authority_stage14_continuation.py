from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "continue-photoreal-v2-source-authority.ps1"


def test_continuation_starts_at_stage14_without_expensive_rework() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "14/16 MEASURE ALL PLANNED FRAMES" in source
    assert "15/16 APPLY CORE SOURCE/IDENTITY AUTHORITY" in source
    assert "16/16 LEAKAGE + HELD-OUT COVERAGE GATE" in source
    assert "photoreal_identity_calibration_cli" not in source
    assert "photoreal_identity_calibration_extractor_cli" not in source
    assert "photoreal_identity_negative_inventory_cli" not in source
    assert "photoreal_source_verify_cli" not in source
    assert "Source rehash:     NO" in source
    assert "Negative sampling: NO" in source
    assert "Calibration rerun: NO" in source


def test_continuation_requires_persisted_uncalibrated_authority_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "identity-calibration.json" in source
    assert "identity_matching_authorized -ne $false" in source
    assert "match_threshold_calibrated -ne $false" in source
    assert "$null -ne $calibration.match_threshold" in source
    assert "stash-single-performer-target-binding-v1" in source
    assert "calibrated_identity_verified_count" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source


def test_continuation_copies_reused_authority_artifacts_with_hash_verification() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for name in (
        "dataset-plan.json", "source-receipt.json", "scan-plan.json",
        "model-set.json", "identity-bank.json", "identity-calibration.json",
        "source-resume-receipt.json",
    ):
        assert name in source
    assert "Get-FileHash -LiteralPath $source -Algorithm SHA256" in source
    assert "Get-FileHash -LiteralPath $destination -Algorithm SHA256" in source
    assert "Copied authority artifact changed" in source


def test_continuation_parses_when_pwsh_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(SCRIPT)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert completed.returncode == 0, completed.stderr
