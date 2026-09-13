from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLONE = ROOT / "clone-body.ps1"


def test_clone_body_uses_bool_safe_v1_guard_for_persisted_manifests() -> None:
    source = CLONE.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    assert "Test-V1Version $manifest.version" in source
    assert "Test-V1Version $overrideManifest.version" in source
    assert "[int]$manifest.version" not in source
    assert "[int]$overrideManifest.version" not in source


def test_clone_body_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    clone = str(CLONE.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{clone}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{
    $errors | ForEach-Object {{ Write-Error $_.Message }}
    exit 20
}}
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


def test_clone_body_keeps_source_and_segment_integrity_bindings() -> None:
    source = CLONE.read_text(encoding="utf-8")

    assert 'if ([string]$manifest.source_kind -ne "stash-local")' in source
    assert '$sourcePerformerId = [string]$manifest.performer.id' in source
    assert '$sourcePerformerName = [string]$manifest.performer.name' in source
    assert 'Get-FileHash -Algorithm SHA256 -LiteralPath $segmentPath' in source
    assert 'if ($actualHash -ne $expectedHash)' in source
    assert 'from bodyrig.portable_identity import source_set_sha256' in source
    assert '"--expected-source-set-sha256", $sourceSetSnapshot' in source
