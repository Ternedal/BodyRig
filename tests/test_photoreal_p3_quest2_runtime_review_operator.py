from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-quest2-runtime-review.ps1"


def test_modular_runtime_review_operator_requires_clean_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source


def test_modular_runtime_review_operator_consumes_final_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "p3-device-distillation-execution-receipt.json" in source
    assert "p3-quest2-final-workspace-receipt.json" in source
    assert 'Join-Path $FinalWorkspace "output"' in source
    assert "Student bytes:            REVERIFY NOW" in source


def test_modular_runtime_review_operator_stays_pre_physical() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "physical_device_installation_required",
        "physical_device_evidence_required",
        "physical_device_evidence_present",
        "human_runtime_visual_acceptance_required",
        "runtime_review_ready",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_modular_runtime_review_operator_uses_sibling_review_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"p3-quest2-runtime-review"' in source
    assert "Quest2 runtime review workspace already exists" in source


def test_modular_runtime_review_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
