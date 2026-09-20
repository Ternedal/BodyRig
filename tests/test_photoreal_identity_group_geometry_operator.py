from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "diagnose-photoreal-v2-identity-group-geometry.ps1"


def test_group_geometry_operator_preserves_diagnostic_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "IDENTITY GROUP GEOMETRY DIAGNOSTIC" in source
    assert "Source rehash:  NO" in source
    assert "per-group cohesion, LGO, positive neighbors, negative overlap" in source
    assert "identity-extractor\\request.json" in source
    assert "identity-calibration-extractor\\request.json" in source
    assert (
        "identity-calibration-extractor\\output\\negative-observations.json"
        in source
    )
    assert "--identity-request-origin" in source
    assert "--calibration-request-origin" in source
    assert "--negative-observations" in source
    assert "--diagnostic-recognizer-root" in source
    assert "identity-group-geometry-diagnostic" in source
    assert "DIAGNOSTIC ONLY / FALSE" in source
    assert (
        "no identity matching, training, photoreal or production authority"
        in source
    )
    assert "import base64" in source
    assert "[Convert]::FromBase64String($encoded)" in source


def test_group_geometry_operator_powershell_parses_when_pwsh_available() -> None:
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
