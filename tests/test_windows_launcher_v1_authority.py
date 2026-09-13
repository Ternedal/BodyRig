from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "start-windows.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_windows_launcher_uses_bool_safe_numeric_v1() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $config.version" in SCRIPT
    assert "Test-V1Version $state.version" in SCRIPT
    assert "[int]$config.version" not in SCRIPT
    assert "[int]$state.version" not in SCRIPT


def test_stash_contract_is_checked_before_dpapi_restore() -> None:
    restore = SCRIPT.index("function Restore-StashLocalConfig")
    contract = SCRIPT.index('bodyrig-local-stash-config', restore)
    version = SCRIPT.index("Test-V1Version $config.version", contract)
    saved_url = SCRIPT.index("$savedUrl = [string]$config.url", version)
    decrypt = SCRIPT.index("ConvertTo-SecureString ([string]$config.api_key_dpapi)", saved_url)
    zero = SCRIPT.index("ZeroFreeBSTR", decrypt)
    assert restore < contract < version < saved_url < decrypt < zero


def test_launch_state_contract_precedes_checkout_and_pid_trust() -> None:
    reader = SCRIPT.index("function Read-LaunchState")
    contract = SCRIPT.index('bodyrig-ui-service', reader)
    version = SCRIPT.index("Test-V1Version $state.version", contract)
    assertion = SCRIPT.index("function Assert-CurrentLaunchState", version)
    root_revision = SCRIPT.index("$State.revision -ne $ExpectedHead", assertion)
    pid = SCRIPT.index("$pidValue = [int]$State.pid", root_revision)
    assert reader < contract < version < assertion < root_revision < pid


def test_windows_launcher_preserves_checkout_and_secret_authority() -> None:
    for boundary in (
        "bodyrig.__file__",
        "git rev-parse HEAD",
        "git status --porcelain",
        "Produktstart kræver et clean checkout",
        "ConvertFrom-SecureString $secure",
        "SecureStringToBSTR",
        "ZeroFreeBSTR",
        "STASH_URL.Trim()",
        "bodyrig-ui-service",
        "Get-BodyRigHealth",
        "[string]$Health.service -ne \"bodyrig\"",
        "$State.revision -ne $ExpectedHead",
        "Get-Process -Id $pidValue",
        "Move-Item -LiteralPath $temp -Destination $StatePath -Force",
    ):
        assert boundary in SCRIPT



def test_windows_launcher_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    escaped = str(SCRIPT_PATH.resolve()).replace("'", "''")
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
