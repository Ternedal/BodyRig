from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-subject-anatomy-physical-gate.ps1"


def test_physical_gate_revalidates_package_fidelity_result_before_render() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '$packageResult.high_fidelity_ready -ne $false' in source
    assert '$packageResult.face_secondary_ready -ne $false' in source
    assert '$packageResult.face_secondary_blockers' in source
    assert 'Subject anatomy package result violates the high-fidelity fail-closed authority boundary.' in source
    assert '$packageResult.production_activation -ne $false' in source


def test_physical_gate_summary_preserves_nested_face_secondary_blockers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    summary_start = source.index('$summary = [ordered]@{')
    summary_end = source.index('Write-Summary -Path $summaryPath -Value $summary')
    summary = source[summary_start:summary_end]

    assert 'high_fidelity_ready = $false' in summary
    assert 'face_secondary_ready = $false' in summary
    assert 'face_secondary_blockers = @($packageResult.face_secondary_blockers)' in summary
    assert 'human_review_required = $true' in summary
    assert 'production_activation = $false' in summary
