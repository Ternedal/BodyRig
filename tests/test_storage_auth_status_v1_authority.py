from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "storage-auth-status.ps1"
ROUTER = ROOT / "bodyrig-status.ps1"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_storage_status_and_router_use_bool_safe_numeric_v1() -> None:
    status = _source(STATUS)
    router = _source(ROUTER)

    for source in (status, router):
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source

    for reader in ("$storage.version", "$stash.version", "$pre.version", "$cold.version"):
        assert f"Test-V1Version {reader}" in status
        assert f"[int]{reader}" not in status

    assert "Test-V1Version $storage.version" in router
    assert "[int]$storage.version" not in router


def test_storage_status_requires_canonical_stash_contract_before_host_authority() -> None:
    status = _source(STATUS)
    stash_guard = status.index('[string]$stash.format -ne "bodyrig-local-stash-config"')
    stash_version = status.index("Test-V1Version $stash.version", stash_guard)
    stash_uri = status.index("$stashUri = [Uri]([string]$stash.url)", stash_version)
    host_authority = status.index("[string]::Equals($stashUri.Host", stash_uri)
    assert stash_guard < stash_version < stash_uri < host_authority


def test_storage_status_preserves_qualification_authority() -> None:
    status = _source(STATUS)
    for boundary in (
        "$storage.credential_write_completed -ne $true",
        "Get-BodyRigDomainCredentialMaxPersist",
        "Test-BodyRigDomainCredential",
        '"bodyrig-storage-pre-reboot-proof"',
        '"bodyrig-storage-cold-boot-proof"',
        "$pre.fresh_smb_session_proved -ne $true",
        "$pre.real_stash_source_decode -ne $true",
        "$required -lt 2",
        '$cold.qualified -eq $true',
        'Emit-Status -State "qualified" -Stage "complete"',
        "This boot has already been counted",
        "verify-storage-auth-after-reboot.ps1",
    ):
        assert boundary in status


def test_top_level_router_blocks_before_profiled_physical_preflight() -> None:
    router = _source(ROUTER)
    storage_call = router.index("& $storageAuthStatus -PerformerId $PerformerId -Json")
    contract = router.index('bodyrig-storage-auth-status', storage_call)
    version_guard = router.index("Test-V1Version $storage.version", contract)
    qualification = router.index("$storage.qualified -ne $true", version_guard)
    blocked_exit = router.index("exit 3", qualification)
    physical = router.index("Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun", blocked_exit)
    assert storage_call < contract < version_guard < qualification < blocked_exit < physical


@pytest.mark.parametrize("script_path", [STATUS, ROUTER])
def test_storage_status_v1_guard_runtime_semantics(script_path: Path) -> None:
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
