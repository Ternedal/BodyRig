from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run-fidelity-v5-review.ps1"


def test_review_runner_reuses_existing_renders_only() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert 'run-fidelity-v5-reanalysis.ps1' in source
    assert 'run-fidelity-silhouette-diagnostics.ps1' in source
    assert 'No Unity render and no SiTH reconstruction will be started.' in source
    assert 'run-fidelity-windows-render-probe.ps1' not in source
    assert 'clone-body-from-stash-profiled-ready.ps1' not in source
    assert 'run-profiled-fidelity-convergence.ps1' not in source


def test_review_runner_requires_both_output_authorities() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert 'reanalysis-v5-$tag' in source
    assert 'silhouette-diagnostics-$tag' in source
    assert 'convergence-decision.json' in source
    assert 'completed without convergence decision evidence' in source
    assert 'completed without silhouette diagnostic evidence' in source
