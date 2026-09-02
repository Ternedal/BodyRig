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


def test_person_studio_surfaces_package_bound_four_view_body_review() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    gallery = Path("bodyrig/ui/body_review_gallery.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/body_review_gallery.css").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    jobs = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")

    assert '/ui/body_review_gallery.css' in html
    assert '/ui/body_review_gallery.js' in html
    assert '/body/review?revision=' in gallery
    for view in ('front-full', 'three-quarter-full', 'side-full', 'face-front'):
        assert view in gallery
    assert '4/4 hash-bundet' in gallery
    assert 'Fail-closed' in gallery
    assert 'ikke identitetsverifikation eller production acceptance' in gallery
    assert '.body-review-grid' in css

    assert '@app.get("/api/v1/people/{person_id}/body/review")' in app
    assert '@app.get("/api/v1/people/{person_id}/body/review/{view}")' in app
    assert 'review_image_path(' in app

    # A UI-created physical candidate must pass renderer capture + persisted
    # review evidence before the body revision is registered in Person Studio.
    fidelity_index = jobs.index('run-fidelity-windows-render-probe.ps1')
    review_index = jobs.index('persist_review(')
    revision_index = jobs.index('updated = add_body_revision(')
    assert fidelity_index < review_index < revision_index
