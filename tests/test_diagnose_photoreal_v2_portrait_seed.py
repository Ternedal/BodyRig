from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "diagnose-photoreal-v2-portrait-seed.ps1"


def test_portrait_seed_operator_is_diagnostic_only_and_uses_pinned_stack() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "bodyrig.stash_fidelity_reference_cli" in source
    assert "photoreal_portrait_seed_diagnostic.py" in source
    assert "identity-bank.json" in source
    assert "reference-models" in source
    assert "Ubuntu-22.04" in source
    assert "cuda:0" in source
    assert "DIAGNOSTIC ONLY / FALSE" in source
    assert "Production:   FALSE" in source
    assert "no matching, training, photoreal or production authority" in source
    assert "teacher_training_authorized = $true" not in source
    assert "production_activation = $true" not in source


def test_portrait_seed_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(SCRIPT)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_portrait_seed_wsl_path_bridge_is_codepage_independent() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import base64" in source
    assert 'base64.b64encode(value.encode("utf-8")).decode("ascii")' in source
    assert "[Convert]::FromBase64String($encoded)" in source
    assert "[Text.Encoding]::UTF8.GetString" in source
    assert "print(make_wsl_path_converter" not in source
