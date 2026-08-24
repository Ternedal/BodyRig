from pathlib import Path


def test_person_studio_surfaces_persisted_restart_safe_body_job_status() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/body_job_status.js").read_text(encoding="utf-8")
    jobs = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")

    assert '/ui/body_job_status.js' in html
    assert '/api/v1/jobs?person_id=' in js
    assert 'queued' in js and 'running' in js and 'succeeded' in js
    assert 'failed' in js and 'canceled' in js and 'interrupted' in js
    assert 'Fail-closed' in js
    assert 'genstartes aldrig automatisk' in js
    assert 'MutationObserver' in js
    assert 'visibilitychange' in js

    assert 'job.get("status") in {"queued", "running"}' in jobs
    assert 'job["status"] = "interrupted"' in jobs
    assert 'service restarted before the UI job reached a terminal state' in jobs
