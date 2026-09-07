from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bodyrig" / "resume_body_job.py").read_text(encoding="utf-8")
WRAPPER = (ROOT / "resume-body-job.ps1").read_text(encoding="utf-8")


def test_assessment_exercises_real_gate_a_without_persistent_output() -> None:
    assert "def assess_body_job_resume" in SOURCE
    assert 'TemporaryDirectory(prefix="bodyrig-gate-a-resume-assessment-")' in SOURCE
    assert '"persistent_mutation": False' in SOURCE
    assert '"recovery_rerun": False' in SOURCE
    assert '"fitter_rerun": False' in SOURCE
    assert '"--assess-only"' in SOURCE
    assert "[switch]$AssessOnly" in WRAPPER
    assert 'if ($AssessOnly) { $argsList += "--assess-only" }' in WRAPPER


def test_real_resume_builds_replacement_gate_a_before_quarantine() -> None:
    segment = SOURCE[SOURCE.index("def resume_body_job(job_id: str)") :]

    stage = segment.index("staged_acceptance =")
    gate = segment.index("gate = resume_gate_a(")
    quarantine = segment.index(
        'quarantined_acceptance = _quarantine_partial(acceptance_dir, label="previous Gate A")'
    )
    promotion = segment.index("os.replace(staged_acceptance, acceptance_dir)")
    fidelity = segment.index("run-fidelity-windows-render-probe.ps1")

    assert stage < gate < quarantine < promotion < fidelity
    assert 'f"{acceptance_dir.name}.resume-staging-{uuid.uuid4().hex}"' in segment
    assert "canonical Gate A destination unexpectedly exists after quarantine" in segment


def test_resume_still_never_reruns_clone_recovery_or_fitter() -> None:
    segment = SOURCE[SOURCE.index("def resume_body_job(job_id: str)") :]

    assert 'resumed_without_clone_rerun"] = True' in segment
    assert "clone-body-from-stash" not in segment
    assert "external_fitter" not in segment
    assert '"recovery_rerun": False' not in segment  # Gate A result owns this invariant.
