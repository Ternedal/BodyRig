from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "prepare-photoreal-v2-identity-group-review.ps1"
ATTEST = ROOT / "record-photoreal-v2-identity-group-attestation.ps1"


def test_identity_group_review_operators_preserve_human_authority_boundary() -> None:
    prepare = PREPARE.read_text(encoding="utf-8")
    attest = ATTEST.read_text(encoding="utf-8")

    assert "REVIEW CANDIDATES ONLY / FALSE" in prepare
    assert "Authority:    FALSE until explicit complete human attestation" in prepare
    assert "identity-extractor\\request.json" in prepare
    assert "portrait-seed-diagnostic-*" in prepare
    assert "BODYRIG_REVISION=" in prepare

    assert "-ConfirmIdentity" in attest
    assert "AcceptGroup" in attest
    assert "RejectGroup" in attest
    assert "Group selection authority: TRUE" in attest
    assert "Identity matching:          FALSE" in attest
    assert "Teacher training:           FALSE" in attest
    assert "Production:                 FALSE" in attest


@pytest.mark.parametrize("script", [PREPARE, ATTEST])
def test_identity_group_review_operator_powershell_parses_when_pwsh_available(
    script: Path,
) -> None:
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
    env["BODYRIG_PARSE_SCRIPT"] = str(script)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
