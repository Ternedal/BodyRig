from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "configure-stash-path-map.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_stash_path_map_uses_bool_safe_numeric_v1() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $config.version" in SCRIPT
    assert "[int]$config.version" not in SCRIPT


def test_stash_config_contract_precedes_url_key_and_discovery_authority() -> None:
    config_read = SCRIPT.index("$config = Get-Content -LiteralPath $ConfigPath")
    contract = SCRIPT.index('bodyrig-local-stash-config', config_read)
    version = SCRIPT.index("Test-V1Version $config.version", contract)
    stash_url = SCRIPT.index("$stashUrl = [string]$config.url", version)
    protected_key = SCRIPT.index("$protectedKey = [string]$config.api_key_dpapi", stash_url)
    cache = SCRIPT.index("bodyrig.stash_path_cache", protected_key)
    decrypt = SCRIPT.index("ConvertTo-SecureString $protectedKey", cache)
    graphql = SCRIPT.index("function Invoke-StashGraphQl", decrypt)
    assert config_read < contract < version < stash_url < protected_key < cache < decrypt < graphql


def test_stash_path_map_preserves_secret_scope_and_evidence_authority() -> None:
    for boundary in (
        "SecureStringToBSTR",
        "ZeroFreeBSTR",
        "Write-Host $apiKey",
        "$scopeHasher = [System.Security.Cryptography.SHA256]::Create()",
        "stash-path-map-performer-$scopeHash.json",
        "$cacheEvidencePaths += $globalEvidencePath",
        '"--performer-id", [string]$performerIdItem',
        "$cache.ok -eq $true",
        "Set-BodyRigStashPathMap -Mapping $cachedMapping -PersistUser",
        "Test-Path -LiteralPath $candidate -PathType Leaf",
        "$bestHits -gt 0",
        'format = "bodyrig-local-stash-path-map"',
        "version = 2",
        "stash_origin = $stashOrigin",
        "performer_ids = @($performerIds)",
        "Move-Item -LiteralPath $temp -Destination $evidencePath -Force",
    ):
        if boundary == "Write-Host $apiKey":
            assert boundary not in SCRIPT
        else:
            assert boundary in SCRIPT


def test_stash_path_map_config_guard_precedes_dpapi_decryption() -> None:
    guard = SCRIPT.index("Test-V1Version $config.version")
    decrypt = SCRIPT.index("ConvertTo-SecureString $protectedKey")
    assert guard < decrypt


def test_stash_path_map_v1_guard_runtime_semantics() -> None:
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
