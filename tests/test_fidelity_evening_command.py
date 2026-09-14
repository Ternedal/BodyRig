from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_command_delegates_to_canonical_current_floor_review() -> None:
    text = source()

    assert "run-fidelity-evening-current-floor-review.ps1" in text
    assert "Current-floor evening review failed" in text
    assert "current_floor_refit_repackage" in text
    assert "expensive_reconstruction_rerun" in text
    assert "physical_acceptance_authority" in text
    assert "human_visual_authority_required" in text
    assert "production_activation" in text


def test_evening_summary_v1_guard_is_bool_safe_before_summary_authority() -> None:
    text = source()

    assert "function Test-V1Version($Value)" in text
    assert "$Value -is [bool]" in text
    assert "$Value -isnot [ValueType]" in text
    assert "[decimal]$Value -eq [decimal]1" in text
    assert "Test-V1Version $summary.version" in text
    assert "[int]$summary.version" not in text

    summary_read = text.index('$summary = Read-Json -Path $summaryPath -Label "Current-floor evening summary"')
    version_guard = text.index("Test-V1Version $summary.version", summary_read)
    package_guard = text.index("[string]$summary.bodyrig_revision -ne $head", version_guard)
    selected = text.index("$summary.selected_candidate", package_guard)
    assert summary_read < version_guard < package_guard < selected


def _v1_helper_source() -> str:
    text = source()
    start = text.index("function Test-V1Version($Value)")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_evening_summary_v1_guard_runtime_rejects_coercive_values() -> None:
    script = _v1_helper_source() + r'''
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


def test_evening_command_recomputes_exact_component_gap_before_reuse() -> None:
    text = source()

    assert "bodyrig.fidelity_component_gap" in text
    assert "--visibility-probe $visibility" in text
    assert "--render-set $renderSet" in text
    assert "$gapAttempt" in text
    assert "Fresh current-floor component gap plan" in text
    assert "Revalidated existing component gap plan" in text
    assert "Assert-SemanticallyEqualJson -Expected $freshGap -Actual $existingGap" in text
    assert "differs from freshly recomputed authority; refusing stale/tampered reuse" in text


def test_evening_command_binds_gap_to_current_floor_package_and_revision() -> None:
    text = source()

    assert '[string]$gap.bodyrig_revision -ne $head' in text
    assert '[string]$gap.package_sha256 -ne $physicalPackageSha' in text
    assert "$gap.human_visual_authority_required -ne $true" in text
    assert "$gap.production_activation -ne $false" in text


def test_evening_command_prints_qualified_operator_result() -> None:
    text = source()

    assert "BODYRIG EVENING RESULT" in text
    assert "Drawable:" in text
    assert "Missing:" in text
    assert "Strict scoring:" in text
    assert "Qualified next actions:" in text
    assert "foreach ($action in $actions)" in text
    assert "$action.id" in text
    assert "$action.reason" in text
    assert "Human visual QA: REQUIRED" in text
    assert "Production:      FALSE" in text
    assert "Snapshots:" in text
    assert "Start-Process explorer.exe" in text


def test_evening_command_does_not_introduce_clone_or_reconstruction_paths() -> None:
    text = source()

    for forbidden in (
        "clone-body-from-stash",
        "run-profiled-fidelity-convergence",
        '"-m", "bodyrig.sith_reconstruct"',
        "reconstruct_sith(",
        "SithSeed",
    ):
        assert forbidden not in text
