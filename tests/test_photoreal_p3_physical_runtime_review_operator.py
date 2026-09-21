from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoreal-v2-p3-physical-runtime-review.ps1"


def test_physical_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_physical_operator_requires_real_operator_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "operator_supplied" in source
    assert "physical_device_observed" in source
    assert "confirm_physical_device_review_complete" in source


def test_physical_operator_preserves_pass_fail_and_never_production() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '$status -eq "pass"' in source
    assert '$status -eq "fail"' in source
    assert "runtime_acceptance_authority" in source
    assert "photoreal_acceptance_authority" in source
    assert "production_activation" in source
    assert "Production activation:     FALSE" in source


def test_physical_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
