from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-quest-runtime.ps1"


def test_runtime_operator_requires_clean_main_and_core_receipt() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert "p3-device-distillation-execution-receipt.json" in source
    assert 'Join-Path $executionRoot "output"' in source


def test_runtime_operator_targets_existing_reference_loader_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "bodyrig-runtime-assets-v1" in source
    assert "runtime-manifest.json" in source
    assert "student_bytes_reverified_before_copy" in source
    assert "runtime_bytes_reverified_after_copy" in source


def test_runtime_operator_keeps_photoreal_and_production_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "physical_device_review_required" in source
    assert "runtime_acceptance_authority" in source
    assert "photoreal_acceptance_authority" in source
    assert "production_activation" in source


def test_runtime_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
