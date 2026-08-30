from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "run-profiled-fidelity-to-renderer-ready.ps1"


def test_profiled_fidelity_launcher_delegates_only_to_canonical_stages() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"clone-body-from-stash-profiled-ready.ps1"' in source
    assert '"accept-physical-clone.ps1"' in source
    assert '"check-reference-renderer-ready.ps1"' in source
    assert '"run-reference-windows-renderer-probe.ps1"' in source

    assert '"clone-body-from-stash.ps1"' not in source
    assert '"clone-body.ps1"' not in source
    assert "-AllowDirty" not in source
    assert "-AllowCpu" not in source
    assert "-SkipObservationSelection" not in source

    clone = source.index("Invoke-CanonicalScript -Script $profiledClone")
    gate_a = source.index("Invoke-CanonicalScript -Script $gateA")
    renderer_ready = source.index("Invoke-CanonicalScript -Script $rendererReady")
    next_human_gate = source.index("NEXT HUMAN GATE")

    assert clone < gate_a < renderer_ready < next_human_gate


def test_profiled_fidelity_launcher_uses_one_run_root_and_explicit_evidence_paths() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"BodyRig\\profiled-fidelity-runs\\$BodyId-$stamp-$suffix"' in source
    assert '$sessionReport = Join-Path $RunRoot "physical-session.json"' in source
    assert '$cloneOutput = Join-Path $RunRoot "clone-output"' in source
    assert '$acceptanceDir = Join-Path $cloneOutput "acceptance"' in source
    assert '"-OutputDir", $cloneOutput' in source
    assert '"-SessionReport", $sessionReport' in source
    assert '"-SessionReport", $sessionReport' in source
    assert '"-OutputDir", $acceptanceDir' in source
    assert 'Join-Path $acceptanceDir "bodyrig-acceptance.json"' in source


def test_profiled_fidelity_launcher_preserves_human_visual_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Fresh clone and Gate A are complete; no human renderer acceptance has been claimed." in source
    assert '.\\run-reference-windows-renderer-probe.ps1 -AcceptanceDir' in source
    assert "If Windows visual quality fails, stop there; do not proceed to Quest/final activation." in source


def test_profiled_fidelity_launcher_keeps_generated_evidence_outside_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "RunRoot must be outside the BodyRig checkout" in source
    assert "RunRoot already exists; refusing cross-run evidence reuse" in source
    assert "git -C $repoRoot status --porcelain" in source
    assert "requires an exact clean checkout" in source
