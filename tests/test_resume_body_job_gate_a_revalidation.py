from __future__ import annotations

from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "bodyrig" / "resume_body_job.py").read_text(encoding="utf-8")


def test_every_resume_revalidates_gate_a_from_producer_evidence() -> None:
    assert 'quarantined_acceptance = _quarantine_partial(acceptance_dir, label="previous Gate A")' in SOURCE
    assert 'gate = resume_gate_a(' in SOURCE
    assert 'existing Gate A acceptance' not in SOURCE
    assert 'if not (acceptance_dir / "bodyrig-acceptance.json").is_file()' not in SOURCE


def test_resume_still_never_reruns_clone_or_fitter() -> None:
    assert 'resumed_without_clone_rerun"] = True' in SOURCE
    assert "clone-body-from-stash" not in SOURCE
    assert "external_fitter" not in SOURCE
