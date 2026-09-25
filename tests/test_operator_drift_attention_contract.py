from pathlib import Path


def _js() -> str:
    return Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_drift_attention_uses_latest_job_per_person_and_kind() -> None:
    js = _js()

    assert "function latestByKey(" in js
    assert "function jobAttention(" in js
    assert '${job.kind || "job"}::${job.person_id || "global"}' in js
    assert 'job.created_utc || job.started_utc || job.completed_utc || ""' in js
    assert '["failed", "interrupted"].includes(String(job.status))' in js
    assert 'ACTION_JOB_STATES.has(String(job.status))' in js
    assert "seneste spor fejlet/afbrudt" in js
    assert "kræver input" in js


def test_drift_attention_uses_latest_launch_per_category_and_gate() -> None:
    js = _js()

    assert "function launchAttention(" in js
    assert 'context.gate || context.action || ""' in js
    assert '${launch.category || "operator"}::${gate}' in js
    assert 'launch.started_utc || launch.finished_utc || ""' in js
    assert 'String(launch.state) === "failed"' in js
    assert 'String(launch.state) === "unknown"' in js
    assert "seneste fejl" in js
    assert "seneste ukendte" in js


def test_drift_top_summary_combines_service_and_operational_attention() -> None:
    js = _js()

    assert "const jobsAttention = jobAttention(jobs);" in js
    assert "const launchesAttention = launchAttention(launches);" in js
    assert "if (jobsAttention) attention.push(jobsAttention);" in js
    assert "if (launchesAttention) attention.push(launchesAttention);" in js
    assert '${attention.length} områder kræver opmærksomhed: ${attention.join(", ")}.' in js
    assert "runtime, jobs og operator authority er grønne." in js
