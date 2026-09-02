from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "body_job_progress.js").read_text(encoding="utf-8")


def test_person_studio_loads_body_progress_detail_layer() -> None:
    assert '<script src="/ui/body_job_progress.js" defer></script>' in HTML
    assert 'id="bodyJobProgressBar"' in JS
    assert 'id="bodyJobProgressText"' in JS
    assert 'id="bodyJobDiagnosticTail"' in JS


def test_progress_is_backend_evidence_based_not_fake_eta() -> None:
    assert "job.progress" in JS
    assert 'job.progress_kind === "pipeline-phase-estimate-v1"' in JS
    assert "pipeline-evidence" in JS
    assert "ETA" in JS
    assert "Date.now()" not in JS


def test_grouped_reconstruction_phase_does_not_pretend_sith_already_started() -> None:
    assert 'job?.stage === "high_fidelity_reconstruction"' in JS
    assert "PHALP/4D-Humans" in JS
    assert "Recovery/identity/high-fidelity pipeline" in JS
    assert "Do not pretend" in JS


def test_failed_job_surfaces_backend_diagnostic_tail() -> None:
    assert "job.diagnostic_tail" in JS
    assert "FAILURE.has(job.status)" in JS
    assert 'diagnostic.classList.remove("hidden")' in JS


def test_active_body_progress_polls_without_mutating_job_state() -> None:
    assert '/api/v1/jobs?person_id=' in JS
    assert 'cache: "no-store"' in JS
    assert "method: \"POST\"" not in JS
    assert "method: 'POST'" not in JS
