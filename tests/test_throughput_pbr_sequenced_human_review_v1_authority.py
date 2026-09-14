from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-throughput-human-review-from-ab-plan.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_outer_throughput_human_review_uses_bool_safe_v1_at_all_authority_readers() -> None:
    assert "function Test-V1Version($Value)" in SOURCE
    assert "Test-V1Version $value.version" in SOURCE
    assert "Test-V1Version $Gate.version" in SOURCE
    assert "Test-V1Version $Continuation.version" in SOURCE
    assert "Test-V1Version $intermediate.version" in SOURCE

    for coercive in (
        "[int]$value.version",
        "[int]$Gate.version",
        "[int]$Continuation.version",
        "[int]$intermediate.version",
    ):
        assert coercive not in SOURCE


def test_outer_throughput_human_review_preserves_fail_closed_bindings_and_nonactivation() -> None:
    for marker in (
        'bodyrig-pbr-human-review-gate-context',
        'bodyrig-throughput-pbr-human-review-gate',
        'bodyrig-throughput-plan-bound-review-continuation',
        'bodyrig-throughput-plan-bound-human-review-authority',
        'bodyrig-throughput-pbr-sequenced-human-review-authority',
        'Assert-GateMatchesProbe -Gate $gate -Probe $probeBefore',
        'Assert-GateMatchesProbe -Gate $gate -Probe $probeAfter',
        'Assert-GateMatchesProbe -Gate $gate -Probe $terminalProbe',
        '[string]$Continuation.stash_performer_id -ne [string]$Gate.stash_performer_id',
        '[string]$Continuation.pbr_gate_receipt_sha256 -ne $GateSha',
        '[string]$intermediate.candidate_run_plan_sha256 -ne $runPlanSha',
        'Throughput continuation authority changed during internal human review.',
        'Sequenced throughput authority inputs changed before terminal publication.',
        'comparison_only = $true',
        'physical_acceptance_authority = $false',
        'promotion_authority = $false',
        'production_activation = $false',
    ):
        assert marker in SOURCE


def _helper_source() -> str:
    start = SOURCE.index("function Test-V1Version($Value)")
    end = SOURCE.index("\n}\n", start) + 3
    return SOURCE[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is unavailable")
def test_outer_throughput_human_review_v1_guard_runtime_semantics() -> None:
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
