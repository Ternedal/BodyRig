from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "collect-photoidentity-evidence.ps1"
COLLECTOR = COLLECTOR_PATH.read_text(encoding="utf-8")


def test_collection_uses_bool_safe_pinned_fitter_v1_before_runtime_derivation() -> None:
    assert "function Test-V1Version($Value)" in COLLECTOR
    assert "$Value -is [bool]" in COLLECTOR
    assert "$Value -isnot [ValueType]" in COLLECTOR
    assert "[decimal]$Value -eq [decimal]1" in COLLECTOR
    assert "Test-V1Version $fitter.version" in COLLECTOR
    assert "[int]$fitter.version" not in COLLECTOR

    guard = COLLECTOR.index("Test-V1Version $fitter.version")
    command = COLLECTOR.index("$fitterCommand = @($fitter.command)", guard)
    distribution = COLLECTOR.index('Need-CommandArgument -Command $fitterCommand -Name "--distribution"', command)
    preflight = COLLECTOR.index("bodyrig.sith_preflight", distribution)
    enrichment = COLLECTOR.index("bodyrig.photoidentity_detail_enrich", preflight)
    assert guard < command < distribution < preflight < enrichment


def test_collection_preserves_pinned_runtime_and_non_authority_boundaries() -> None:
    for boundary in (
        "Photoidentity collection requires an exact clean BodyRig checkout",
        "BodyRig Python imports bodyrig from a different checkout",
        'bodyrig-external-fitter-config',
        '[string]$fitter.adapter -ne "sith-smplx-vrm"',
        '[string]$fitter.revision -ne "1"',
        "/build/examples/openpose/openpose.bin",
        "Pinned SiTH/OpenPose detail runtime preflight failed",
        "Pinned SCHP runtime preflight failed",
        "Photoidentity evidence output must be outside the BodyRig Git checkout",
        "Photoidentity final evidence bundle failed strict validation",
        "no generic guessing; no reconstruction/render authority",
        "Generic guessing permitted: FALSE",
    ):
        assert boundary in COLLECTOR


def _helper_source() -> str:
    start = COLLECTOR.index("function Test-V1Version($Value)")
    end = COLLECTOR.index("\n}\n", start) + 3
    return COLLECTOR[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_collection_v1_helper_runtime_rejects_coercive_values() -> None:
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
