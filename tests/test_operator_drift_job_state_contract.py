from pathlib import Path

import bodyrig.ui_jobs as ui_jobs


def test_drift_open_job_states_match_backend_authority() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    expected = {
        "uploading",
        "queued",
        "running",
        "needs_speaker",
        "needs_reference",
        "cancelling",
    }
    assert ui_jobs._OPEN == expected
    for state in sorted(expected):
        assert f'"{state}"' in js

    assert 'const ACTION_JOB_STATES = new Set(["needs_speaker", "needs_reference"])' in js
    assert 'status !== "cancelling"' in js
    assert 'String(job?.kind || "") === "body-build" && status === "queued"' in js


def test_drift_job_monitoring_surfaces_persisted_evidence_not_time_prediction() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert "job.progress" in js
    assert "job.progress_kind" in js
    assert "pipeline-phase-estimate-v1" in js
    assert "Evidence-backed faseestimat; ikke et tidsestimat." in js
    assert "job.message" in js
    assert "job.error" in js
    assert "job.diagnostic_tail" in js
    assert "job.pid" in js
    assert "job.started_utc" in js
    assert "job.completed_utc" in js


def test_drift_hydrates_open_voice_jobs_and_exposes_typed_disambiguation_actions() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    assert "hydrateOpenVoiceJobs" in js
    assert 'String(job?.kind || "") !== "voice-build"' in js
    assert "OPEN_JOB_STATES.has(status)" in js
    assert '/api/v1/jobs/${encodeURIComponent(jobId)}' in js
    assert "monitoring_error" in js
    assert "Authoritative VoiceRig-status kunne ikke hentes" in js

    assert "renderVoiceJobChoices" in js
    assert "voiceChoiceValid" in js
    assert "anchor.length >= 3 && anchor.length <= 64" in js
    assert "Number.isInteger(selected) && selected >= 1 && selected <= 4" in js
    assert "job.speaker_choices" in js
    assert "job.reference_choices" in js
    assert "choice.preview_wav_base64" in js
    assert "/speaker?anchor=" in js
    assert "/reference?choice=" in js
    assert 'method: "POST"' in js
    assert "Drift vælger aldrig en fallback automatisk" in js
    assert "VoiceRig choice-listen indeholder ingen gyldige valg" in js
    assert "VoiceRig-valg blev afvist" in js

    assert ".operator-voice-choice-list" in css
    assert ".operator-voice-choice-audio" in css

    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    jobs = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")
    assert '@app.post("/api/v1/jobs/{job_id}/speaker")' in app
    assert '@app.post("/api/v1/jobs/{job_id}/reference")' in app
    assert 'job.get("kind") != "voice-build" or job.get("status") != "needs_speaker"' in jobs
    assert 'job.get("kind") != "voice-build" or job.get("status") != "needs_reference"' in jobs
    assert "source_files_for_body(" in jobs
