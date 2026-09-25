from pathlib import Path

from bodyrig import ui_jobs


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
