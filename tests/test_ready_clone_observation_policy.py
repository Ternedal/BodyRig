from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_ready_launcher_blocks_diagnostics_only_observation_skip():
    ready = (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")
    low_level = (ROOT / "clone-body-from-stash.ps1").read_text(encoding="utf-8")

    gate = (
        'if ($SkipObservationSelection) {\n'
        '    throw "-SkipObservationSelection is diagnostics-only and is not allowed by the canonical production physical launcher. '
        'Use clone-body-from-stash.ps1 directly for diagnostics."\n'
        '}'
    )
    repo_bind = '$repoRoot = (Resolve-Path $PSScriptRoot).Path'
    session_start = 'Invoke-SessionCommand -Arguments @(\n    "start",'

    assert gate in ready
    assert ready.index(gate) < ready.index(repo_bind)
    assert ready.index(gate) < ready.index(session_start)

    # The escape hatch intentionally remains available only on the low-level diagnostic wrapper.
    assert '[switch]$SkipObservationSelection' in low_level
    assert '$selectArgs += "--skip-decode-probe"' in low_level
