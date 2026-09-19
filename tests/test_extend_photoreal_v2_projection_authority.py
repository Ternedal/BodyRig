from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "extend-photoreal-v2-projection-authority.ps1"


def test_extension_helper_requires_new_source_attestation_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[switch]$ConfirmNewVr180Equi" in source
    assert "NEW SPATIAL SOURCES ONLY" in source
    assert "--operator-verified-new-vr180-equi" in source
    assert "--prior-authority" in source
    assert "--new-stereo-layout" in source
    assert "Production:       FALSE" in source


def test_extension_helper_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile($env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
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
