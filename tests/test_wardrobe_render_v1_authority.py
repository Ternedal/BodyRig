from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "prepare-wardrobe-render-review.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_wardrobe_render_uses_bool_safe_numeric_v1_at_all_evidence_boundaries() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT

    for variable in ("lineage", "comparison", "machine", "deformation", "manifest"):
        assert f"Test-V1Version ${variable}.version" in SCRIPT
        assert f"[int]${variable}.version" not in SCRIPT


def test_wardrobe_render_preserves_review_only_authority_boundaries() -> None:
    assert '"bodyrig-wardrobe-package-lineage"' in SCRIPT
    assert '"bodyrig-fidelity-comparison-authority"' in SCRIPT
    assert '"bodyrig-renderer-probe"' in SCRIPT
    assert '"bodyrig-deformation-probe"' in SCRIPT
    assert '"bodyrig-wardrobe-render-set"' in SCRIPT
    assert "$comparison.physical_acceptance_authority -ne $false" in SCRIPT
    assert "$lineage.comparison_only -ne $true" in SCRIPT
    assert "$lineage.human_review_required -ne $true" in SCRIPT
    assert "$lineage.production_activation -ne $false" in SCRIPT
    assert '"human-review-diagnostic-not-physical-pass"' in SCRIPT
    assert "deformation_machine_pass = $true" in SCRIPT
    assert "human_review_required = $true" in SCRIPT
    assert "production_activation = $false" in SCRIPT


def test_wardrobe_render_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    script_path = str(SCRIPT_PATH.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors)
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
