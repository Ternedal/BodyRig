from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "discover-photoidentity-anatomy-sources.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_anatomy_discovery_uses_bool_safe_fitter_v1_before_runtime_derivation() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $fitter.version" in SCRIPT
    assert "[int]$fitter.version" not in SCRIPT

    guard = SCRIPT.index("Test-V1Version $fitter.version")
    command = SCRIPT.index("$fitterCommand = @($fitter.command)", guard)
    distribution = SCRIPT.index('Need-CommandArgument -Command $fitterCommand -Name "--distribution"', command)
    preflight = SCRIPT.index("bodyrig.sith_preflight", distribution)
    discovery = SCRIPT.index("bodyrig.photoidentity_anatomy_source_discovery", preflight)
    assert guard < command < distribution < preflight < discovery


def test_anatomy_discovery_preserves_non_authorizing_source_only_boundaries() -> None:
    for boundary in (
        "Anatomy source discovery requires an exact clean BodyRig checkout",
        "BodyRig Python imports from a different checkout",
        'bodyrig-external-fitter-config',
        '[string]$fitter.adapter -ne "sith-smplx-vrm"',
        '[string]$fitter.revision -ne "1"',
        "/build/examples/openpose/openpose.bin",
        "Pinned OpenPose authority preflight failed",
        "source crops only; machine anatomy/rear authority FALSE; no avatar render",
        "No rear/torso/waist sufficiency authority has been granted",
    ):
        assert boundary in SCRIPT


def _helper_source() -> str:
    start = SCRIPT.index("function Test-V1Version($Value)")
    end = SCRIPT.index("\n}\n", start) + 3
    return SCRIPT[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_anatomy_discovery_v1_helper_runtime_rejects_coercive_values() -> None:
    script = _helper_source() + r'''
$values = ConvertFrom-Json -InputObject '[1,1.0,true,false,"1",null,2]'.Replace('\"','"')
$results = @()
foreach ($value in @($values)) { $results += [bool](Test-V1Version $value) }
$results | ConvertTo-Json -Compress
'''
    completed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == [True, True, False, False, False, False, False]
