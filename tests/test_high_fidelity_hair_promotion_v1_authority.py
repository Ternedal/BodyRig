from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bodyrig.high_fidelity_hair_promotion import _v1


ROOT = Path(__file__).resolve().parents[1]
PY_SOURCE = ROOT / "bodyrig" / "high_fidelity_hair_promotion.py"
PS_SCRIPT = ROOT / "build-source-hair-review-runtime.ps1"


def test_hair_promotion_v1_runtime_semantics() -> None:
    assert _v1(1)
    assert _v1(1.0)
    assert not _v1(True)
    assert not _v1(False)
    assert not _v1("1")
    assert not _v1(None)
    assert not _v1(2)


def test_hair_promotion_active_readers_use_bool_safe_v1() -> None:
    source = PY_SOURCE.read_text(encoding="utf-8")

    assert "def _v1(value: Any) -> bool:" in source
    assert "return not isinstance(value, bool) and value == VERSION" in source

    for reader in (
        'job.get("version")',
        'anatomy_summary.get("version")',
        'component.get("version")',
        'combined_bridge.get("version")',
        'combined_runtime.get("version")',
        'bridge.get("version")',
        'value.get("version")',
        'promoted_anatomy_embedded.get("version")',
        'embedded.get("version")',
    ):
        assert f"not _v1({reader})" in source

    assert source.count('not _v1(runtime.get("version"))') >= 2

    for unsafe in (
        'job.get("version") != 1',
        'anatomy_summary.get("version") != 1',
        'component.get("version") != 1',
        'combined_bridge.get("version") != 1',
        'combined_runtime.get("version") != 1',
        'bridge.get("version") != 1',
        'runtime.get("version") != 1',
        'value.get("version") != VERSION',
    ):
        assert unsafe not in source


def test_hair_promotion_preserves_exact_review_and_nonactivation_boundaries() -> None:
    source = PY_SOURCE.read_text(encoding="utf-8")

    for boundary in (
        'rebuilt hair-only bridge does not match the exact hair stage reviewed inside the combined preview',
        'rebuilt["bridge_canonical_sha256"] != prepared["expected_hair_review_bridge_sha256"]',
        'hair promotion input contains review-only eye runtime authority',
        'hair promotion input contains review-only eye geometry',
        'hair promotion input contains review-only eye/cornea material',
        'runtime.get("baseAvatarVrmSha256") != _sha256_bytes(candidate_avatar)',
        'runtime.get("comparisonOnly") is not True',
        'runtime.get("humanReviewRequired") is not True',
        'runtime.get("hairComponentAuthority") is not False',
        'runtime.get("productionActivation") is not False',
        'value.get("production_activation") is not False',
        'audit["production_ready"] is not False',
        '"eyesImported": False',
        '"productionActivation": False',
    ):
        assert boundary in source


def test_hair_only_runtime_builder_uses_bool_safe_numeric_v1() -> None:
    source = PS_SCRIPT.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $binding.version" in source
    assert "Test-V1Version $receipt.version" in source
    assert "[int]$binding.version" not in source
    assert "[int]$receipt.version" not in source


def test_hair_only_runtime_builder_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    script_path = str(PS_SCRIPT.resolve()).replace("'", "''")
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
