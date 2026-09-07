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
    assert "if ($AssessOnly)" in WRAPPER
    assert "-m bodyrig.resume_body_job $JobId --assess-only" in WRAPPER
    assert "-m bodyrig.resume_body_job $JobId" in WRAPPER


def test_real_resume_claims_job_before_staging_and_quarantine() -> None:
    segment = SOURCE[SOURCE.index("def resume_body_job(job_id: str)") :]

    claim = segment.index("claim_path = _acquire_resume_claim(job_id)")
    running = segment.index('current["status"] = "running"')
    stage = segment.index("staged_acceptance =")
    gate = segment.index("gate = resume_gate_a(")
    quarantine = segment.index(
        'quarantined_acceptance = _quarantine_partial(acceptance_dir, label="previous Gate A")'
    )
    promotion = segment.index("os.replace(staged_acceptance, acceptance_dir)")
    fidelity = segment.index("run-fidelity-windows-render-probe.ps1")
    release = segment.index("_release_resume_claim(claim_path)")

    assert claim < running < stage < gate < quarantine < promotion < fidelity < release
    assert 'f"{acceptance_dir.name}.resume-staging-{uuid.uuid4().hex}"' in segment
    assert "canonical Gate A destination unexpectedly exists after quarantine" in segment
    assert "lost persisted job ownership before promotion" in segment


def test_pre_promotion_failure_restores_quarantined_output() -> None:
    segment = SOURCE[SOURCE.index("def resume_body_job(job_id: str)") :]
    assert "if context is not None and not promoted:" in segment
    assert "os.replace(quarantined, canonical)" in segment
    assert 'rollback_errors.append(f"{label} rollback failed: {rollback_exc}")' in segment


def test_resume_still_never_reruns_clone_recovery_or_fitter() -> None:
    segment = SOURCE[SOURCE.index("def resume_body_job(job_id: str)") :]

    assert 'resumed_without_clone_rerun"] = True' in segment
    assert "clone-body-from-stash" not in segment
    assert "external_fitter" not in segment
    assert '"recovery_rerun": False' not in segment  # Gate A result owns this invariant.
