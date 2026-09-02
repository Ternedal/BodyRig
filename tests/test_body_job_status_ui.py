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

    # Physical body jobs cannot prove subprocess authority after a BodyRig restart,
    # so queued/running work remains fail-closed and becomes interrupted.
    assert 'kind == "body-build" and status in {"queued", "running"}' in jobs
    assert 'job["status"] = "interrupted"' in jobs
    assert 'service restarted before the UI job reached a terminal state' in jobs

    # Source-derived VoiceRig work is different: VoiceRig persists its own job
    # authority, so BodyRig can safely reconnect when a remote job id exists.
    assert 'kind == "voice-build" and status in _OPEN and not job.get("voicerig_job_id")' in jobs
    assert 'job.get("kind") == "voice-build" and job.get("status") not in _FINAL' in jobs
    assert 'self._sync_voice_job(job)' in jobs


def test_person_studio_surfaces_source_bound_voicerig_workflow() -> None:
    js = Path("bodyrig/ui/body_job_status.js").read_text(encoding="utf-8")

    assert 'Source-bound VoiceRig' in js
    assert '/voice/build-from-source' in js
    assert 'needs_speaker' in js and 'needs_reference' in js
    assert '/speaker?anchor=' in js and '/reference?choice=' in js
    assert 'Manuelt valgte/importerede VoiceRig-stemmer' in js
    assert 'source-binding' in js
