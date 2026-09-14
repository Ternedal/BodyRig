from pathlib import Path

root = Path(__file__).resolve().parents[1]
script = root / "run-fidelity-evening.ps1"
text = script.read_text(encoding="utf-8")
anchor = '''function Assert-SemanticallyEqualJson {\n    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)\n    $expectedText = $Expected | ConvertTo-Json -Depth 50 -Compress\n    $actualText = $Actual | ConvertTo-Json -Depth 50 -Compress\n    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }\n}\n\nif ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig evening command is Windows-only." }\n'''
replacement = '''function Assert-SemanticallyEqualJson {\n    param([Parameter(Mandatory = $true)]$Expected,[Parameter(Mandatory = $true)]$Actual,[Parameter(Mandatory = $true)][string]$Label)\n    $expectedText = $Expected | ConvertTo-Json -Depth 50 -Compress\n    $actualText = $Actual | ConvertTo-Json -Depth 50 -Compress\n    if ($expectedText -ne $actualText) { throw "$Label differs from freshly recomputed authority; refusing stale/tampered reuse." }\n}\nfunction Test-V1Version($Value) {\n    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }\n    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }\n}\n\nif ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "BodyRig evening command is Windows-only." }\n'''
if text.count(anchor) != 1:
    raise SystemExit("evening summary helper insertion anchor drifted")
text = text.replace(anchor, replacement)
old = '[int]$summary.version -ne 1'
new = '-not (Test-V1Version $summary.version)'
if text.count(old) != 1:
    raise SystemExit("evening summary version guard drifted")
script.write_text(text.replace(old, new), encoding="utf-8", newline="\n")

test = root / "tests" / "test_fidelity_evening_summary_v1_authority.py"
if test.exists():
    raise SystemExit("evening summary v1 regression already exists")
test.write_text("""from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "run-fidelity-evening.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_evening_summary_uses_bool_safe_v1_before_trusting_authority_fields() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $summary.version" in SCRIPT
    assert "[int]$summary.version" not in SCRIPT

    guard = SCRIPT.index("Test-V1Version $summary.version")
    revision = SCRIPT.index("[string]$summary.bodyrig_revision -ne $head", guard)
    package = SCRIPT.index("[string]$gap.package_sha256 -ne [string]$summary.current_floor_package_sha256", revision)
    assert guard < revision < package


def test_evening_summary_preserves_recomputed_gap_and_non_authorizing_boundaries() -> None:
    for boundary in (
        "Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap",
        "differs from freshly recomputed authority; refusing stale/tampered reuse",
        "$summary.current_floor_refit_repackage -ne $true",
        "$summary.expensive_reconstruction_rerun -ne $false",
        "$summary.diagnostic_only -ne $true",
        "$summary.physical_acceptance_authority -ne $false",
        "$summary.human_visual_authority_required -ne $true",
        "$summary.production_activation -ne $false",
        "$gap.human_visual_authority_required -ne $true",
        "$gap.production_activation -ne $false",
    ):
        assert boundary in SCRIPT


def _helper_source() -> str:
    start = SCRIPT.index("function Test-V1Version($Value)")
    end = SCRIPT.index("\n}\n", start) + 3
    return SCRIPT[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_evening_summary_v1_helper_runtime_rejects_coercive_values() -> None:
    ps = _helper_source() + r'''
$values = ConvertFrom-Json -InputObject '[1,1.0,true,false,"1",null,2]'.Replace('\"','"')
$results = @()
foreach ($value in @($values)) { $results += [bool](Test-V1Version $value) }
$results | ConvertTo-Json -Compress
'''
    completed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == [True, True, False, False, False, False, False]
""", encoding="utf-8", newline="\n")
