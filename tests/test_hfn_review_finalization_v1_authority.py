from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDER_PATH = ROOT / "prepare-hands-feet-nails-render-review.ps1"
FINALIZE_PATH = ROOT / "finalize-hands-feet-nails-authority.ps1"
RENDER = RENDER_PATH.read_text(encoding="utf-8")
FINALIZE = FINALIZE_PATH.read_text(encoding="utf-8")


def _assert_v1_helper(source: str) -> None:
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source


def test_render_review_uses_bool_safe_v1_at_both_persisted_authorities() -> None:
    _assert_v1_helper(RENDER)
    assert "Test-V1Version $comparison.version" in RENDER
    assert "Test-V1Version $value.version" in RENDER
    assert "[int]$comparison.version" not in RENDER
    assert "[int]$value.version" not in RENDER

    comparison_guard = RENDER.index("Test-V1Version $comparison.version")
    comparison_hash = RENDER.index("$comparisonPackageSha -ne $packageSha", comparison_guard)
    manifest_guard = RENDER.index("Test-V1Version $value.version")
    views = RENDER.index('@("left_hand", "right_hand", "left_foot", "right_foot")')
    authority = RENDER.index('format = "bodyrig-hands-feet-nails-render-authority"')
    assert comparison_guard < comparison_hash
    assert views < manifest_guard < authority


def test_render_review_preserves_review_only_four_view_authority() -> None:
    for boundary in (
        '"bodyrig-fidelity-comparison-authority"',
        '"validated-package-comparison-only"',
        '"bodyrig-hands-feet-nails-render-set"',
        '"human-review-diagnostic-not-physical-pass"',
        '@("left_hand", "right_hand", "left_foot", "right_foot")',
        'comparison_only = $true',
        'human_review_required = $true',
        'production_activation = $false',
        'Move-Item -LiteralPath $attempt -Destination $output',
    ):
        assert boundary in RENDER


def test_finalizer_uses_bool_safe_render_authority_v1_before_revision_trust() -> None:
    _assert_v1_helper(FINALIZE)
    assert "Test-V1Version $renderValue.version" in FINALIZE
    assert "[int]$renderValue.version" not in FINALIZE

    guard = FINALIZE.index("Test-V1Version $renderValue.version")
    revision = FINALIZE.index("[string]$renderValue.bodyrig_revision -ne $revision", guard)
    review_only = FINALIZE.index("$renderValue.comparison_only -ne $true", revision)
    release_cli = FINALIZE.index("bodyrig.hands_feet_nails_release_authority_cli", review_only)
    assert guard < revision < review_only < release_cli
    assert "$renderValue.human_review_required -ne $true" in FINALIZE
    assert "$renderValue.production_activation -ne $false" in FINALIZE


def _helper_source(source: str) -> str:
    start = source.index("function Test-V1Version($Value)")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


@pytest.mark.parametrize("source", [RENDER, FINALIZE])
@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_hfn_v1_helpers_reject_coercive_values(source: str) -> None:
    script = _helper_source(source) + r'''
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
