from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "test-storage-auth-windows.ps1"
VERIFY = ROOT / "verify-storage-auth-after-reboot.ps1"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_storage_auth_writers_use_bool_safe_numeric_v1() -> None:
    proof = _source(PROOF)
    verify = _source(VERIFY)

    for source in (proof, verify):
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source

    for reader in ("$storage.version", "$stash.version"):
        assert f"Test-V1Version {reader}" in proof
        assert f"[int]{reader}" not in proof

    for reader in ("$storage.version", "$pre.version", "$session.version", "$cold.version"):
        assert f"Test-V1Version {reader}" in verify
        assert f"[int]{reader}" not in verify


def test_storage_auth_writers_preserve_physical_storage_authority() -> None:
    proof = _source(PROOF)
    verify = _source(VERIFY)

    for boundary in (
        '"bodyrig-local-storage-config"',
        '"bodyrig-local-stash-config"',
        "$storage.credential_write_completed -ne $true",
        "Get-BodyRigDomainCredentialMaxPersist",
        "Test-BodyRigDomainCredential",
        "[switch]$ResetConnections",
        "if ($ResetConnections)",
        "Get-SmbConnection",
        "bodyrig.stash_cli probe",
        "real_stash_source_decode = $true",
        "credential_prompt_used = $false",
        "secret_persisted_in_proof = $false",
        'format = "bodyrig-storage-session-proof"',
        'format = "bodyrig-storage-pre-reboot-proof"',
        "required_distinct_post_reboot_boots = 2",
    ):
        assert boundary in proof

    for boundary in (
        '"bodyrig-local-storage-config"',
        '"bodyrig-storage-pre-reboot-proof"',
        '"bodyrig-storage-session-proof"',
        '"bodyrig-storage-cold-boot-proof"',
        "$storage.credential_write_completed -ne $true",
        "different credential generation",
        "ResetConnections = $true",
        "& $testScript @testParameters",
        "$session.existing_connections_reset -ne $true",
        "$session.credential_prompt_used -ne $false",
        "$session.real_stash_source_decode -ne $true",
        "$session.secret_persisted_in_proof -ne $false",
        "has already been counted",
        "$required -lt 2",
        "credential_prompt_permitted = $false",
        "real_stash_source_decode_required = $true",
        "secret_persisted_in_proof = $false",
        "Move-Item -LiteralPath $temp -Destination $coldPath -Force",
    ):
        assert boundary in verify


@pytest.mark.parametrize("script_path", [PROOF, VERIFY])
def test_storage_auth_writer_v1_guard_runtime_semantics(script_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    escaped = str(script_path.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ exit 20 }}
$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V1Version' }}, $true)
if ($null -eq $fn) {{ exit 21 }}
Invoke-Expression $fn.Extent.Text
if (-not (Test-V1Version 1)) {{ exit 31 }}
if (-not (Test-V1Version 1.0)) {{ exit 32 }}
if (Test-V1Version $true) {{ exit 33 }}
if (Test-V1Version $false) {{ exit 34 }}
if (Test-V1Version '1') {{ exit 35 }}
if (Test-V1Version $null) {{ exit 36 }}
if (Test-V1Version 2) {{ exit 37 }}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
