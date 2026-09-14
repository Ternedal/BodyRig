from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "build-subject-anatomy-candidate.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_candidate_uses_bool_safe_high_fidelity_audit_v1_before_audit_trust() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $fidelity.version" in SCRIPT
    assert "[int]$fidelity.version" not in SCRIPT

    guard = SCRIPT.index("Test-V1Version $fidelity.version")
    package = SCRIPT.index("$fidelity.package_sha256", guard)
    body = SCRIPT.index("$fidelity.canonical_body_id", package)
    readiness = SCRIPT.index("$fidelity.high_fidelity_ready -ne $false", body)
    result = SCRIPT.index('format = "bodyrig-subject-anatomy-candidate-result"', readiness)
    assert guard < package < body < readiness < result


def test_candidate_preserves_fail_closed_anatomy_boundaries() -> None:
    for boundary in (
        "Subject anatomy candidate build requires an exact clean BodyRig checkout",
        "Retained reconstruction/source bytes changed during subject anatomy candidate build",
        'stage -eq "subject-anatomy-refit"',
        'stage -eq "bodyprint-adjustment"',
        '"bodyrig-high-fidelity-package-audit"',
        "$fidelity.high_fidelity_ready -ne $false",
        "$fidelity.face_secondary_ready -ne $false",
        '[string]$fidelity.semantic_vertex_map_authority -ne "unavailable"',
        "$fidelity.human_review_required -ne $true",
        "$fidelity.production_ready -ne $false",
        '"eyebrow_appearance", "lip_boundary", "mouth_interior", "teeth", "eyelashes"',
        "bodyprint_adjustment = $false",
        "expensive_reconstruction_rerun = $false",
        "comparison_only = $true",
        "human_review_required = $true",
        "production_activation = $false",
        "High fidelity:  FALSE",
    ):
        assert boundary in SCRIPT


def _helper_source() -> str:
    start = SCRIPT.index("function Test-V1Version($Value)")
    end = SCRIPT.index("\n}\n", start) + 3
    return SCRIPT[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_candidate_v1_helper_rejects_coercive_values() -> None:
    script = _helper_source() + r'''
$values = ConvertFrom-Json -InputObject '[1,1.0,true,false,"1",null,2]'
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
