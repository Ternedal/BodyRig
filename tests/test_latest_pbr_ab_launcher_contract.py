from __future__ import annotations

from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "run-latest-pbr-ab-physical-review.ps1").read_text(encoding="utf-8")


def test_latest_launcher_requires_explicit_body_and_verifies_checkpoint_before_selection() -> None:
    assert '[Parameter(Mandatory = $true)]' in SOURCE
    assert '[ValidatePattern(\'^[a-z0-9æøå_-]{1,160}$\')]' in SOURCE
    assert 'BodyRig\\fidelity-convergence' in SOURCE
    assert 'Sort-Object LastWriteTimeUtc -Descending' in SOURCE
    assert 'bodyrig.fidelity_checkpoint_verify_cli' in SOURCE
    assert 'checkpoint body alias mismatch' in SOURCE
    assert 'newest convergence root whose latest checkpoint passes strict byte verification' in SOURCE


def test_latest_launcher_only_delegates_after_verified_selection() -> None:
    assert 'run-pbr-ab-physical-review.ps1' in SOURCE
    assert 'ConvergenceWorkRoot = $selected' in SOURCE
    assert 'CandidateRef = $CandidateRef' in SOURCE
    assert 'BodyRigPython = $BodyRigPython' in SOURCE
    assert 'No verified retained convergence checkpoint is usable' in SOURCE
    assert 'accept-physical-clone.ps1' not in SOURCE
    assert 'production_activation' not in SOURCE
