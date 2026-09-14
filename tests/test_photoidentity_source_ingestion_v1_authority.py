from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NAIL_PATH = ROOT / "discover-photoidentity-nail-sources.ps1"
UNIVERSE_PATH = ROOT / "audit-photoidentity-source-universe.ps1"
NAIL = NAIL_PATH.read_text(encoding="utf-8")
UNIVERSE = UNIVERSE_PATH.read_text(encoding="utf-8")


def _assert_v1_helper(source: str) -> None:
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source


def test_nail_discovery_uses_bool_safe_pinned_fitter_v1() -> None:
    _assert_v1_helper(NAIL)
    assert "Test-V1Version $fitter.version" in NAIL
    assert "[int]$fitter.version" not in NAIL
    assert 'bodyrig-external-fitter-config' in NAIL
    assert '[string]$fitter.adapter -ne "sith-smplx-vrm"' in NAIL
    assert '[string]$fitter.revision -ne "1"' in NAIL


def test_nail_discovery_preserves_source_only_non_authority_boundary() -> None:
    for boundary in (
        "Nail source discovery requires an exact clean BodyRig checkout",
        "BodyRig Python imports from a different checkout",
        "Refusing cross-revision nail evidence",
        "Pinned OpenPose authority preflight failed",
        "source closeups only; machine nail authority FALSE; no avatar render",
        "No nail sufficiency authority has been granted",
    ):
        assert boundary in NAIL

    fitter_guard = NAIL.index("Test-V1Version $fitter.version")
    command = NAIL.index("$fitterCommand = @($fitter.command)", fitter_guard)
    preflight = NAIL.index("bodyrig.sith_preflight", command)
    discovery = NAIL.index("bodyrig.photoidentity_nail_source_discovery", preflight)
    assert fitter_guard < command < preflight < discovery


def test_source_universe_uses_bool_safe_saved_stash_v1_before_secret_use() -> None:
    _assert_v1_helper(UNIVERSE)
    assert "Test-V1Version $stash.version" in UNIVERSE
    assert "[int]$stash.version" not in UNIVERSE

    read = UNIVERSE.index("$stash = Get-Content -LiteralPath $stashConfigPath")
    contract = UNIVERSE.index('bodyrig-local-stash-config', read)
    version = UNIVERSE.index("Test-V1Version $stash.version", contract)
    url = UNIVERSE.index("$stashUrl = ([string]$stash.url).Trim()", version)
    decrypt = UNIVERSE.index("ConvertTo-SecureString ([string]$stash.api_key_dpapi)", url)
    refresh = UNIVERSE.index("& $pathMap -PerformerId $PerformerId -ForceRefresh", decrypt)
    audit = UNIVERSE.index("bodyrig.photoidentity_source_universe", refresh)
    assert read < contract < version < url < decrypt < refresh < audit


def test_source_universe_preserves_storage_secret_and_non_render_authority() -> None:
    for boundary in (
        "$storage.qualified -ne $true",
        "$storage.cold_boots_passed -lt [int]$storage.cold_boots_required",
        "Source-universe evidence must be outside the BodyRig Git checkout",
        "SecureStringToBSTR",
        "ZeroFreeBSTR",
        '[Environment]::SetEnvironmentVariable("STASH_URL", $oldUrl, "Process")',
        '[Environment]::SetEnvironmentVariable("STASH_API_KEY", $oldKey, "Process")',
        "--performer-id $PerformerId",
        "$result.stash_inventory_exhausted -ne $true",
        "Biometric inference:     FALSE",
        "Generic guessing:        FALSE",
        "Render permitted:        FALSE",
    ):
        assert boundary in UNIVERSE

    assert "Write-Host $apiKey" not in UNIVERSE


@pytest.mark.parametrize("script_path", [NAIL_PATH, UNIVERSE_PATH])
def test_source_ingestion_v1_guard_runtime_semantics(script_path: Path) -> None:
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
