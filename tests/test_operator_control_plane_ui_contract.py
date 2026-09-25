from pathlib import Path


def test_person_studio_has_operations_control_plane() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert 'data-tab="operations"' in html
    assert 'id="tab-operations"' in html
    assert "/ui/operator_control_plane.css" in html
    assert "/ui/operator_control_plane.js" in html
    for endpoint in (
        "/api/v1/health",
        "/api/v1/operator-authority",
        "/api/v1/stash/health",
        "/api/v1/modelrig/health",
        "/api/v1/voicerig/health",
        "/api/v1/runtime/state",
        "/api/v1/jobs",
    ):
        assert endpoint in js
    assert "/cancel" in js
    assert "Annullér" in js
    assert "serviceHealthy" in js
    assert 'value.physical_build_ready === true' in js
    assert 'value.performer_read === true' in js
    assert 'value.wsl_cuda?.ready === true' in js
    assert 'value.powershell_7 === true' in js
    assert 'key === "modelrig" || key === "voicerig"' in js
    assert 'failures.map((item) => item.label).join(", ")' in js
    assert "physical_build_reason" in js
    assert "runtime og operator authority er grønne" in js or "runtime, jobs og operator authority er grønne" in js
    assert 'new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"])' in js
    assert 'new Set(["needs_speaker", "needs_reference"])' in js
    assert "jobCanCancel" in js
    assert 'String(job?.kind || "") === "body-build" && status === "queued"' in js
    assert 'String(job?.kind || "") === "voice-build"' in js
    assert "diagnostic_tail" in js
    assert "progress_kind" in js
    assert "pipeline-phase-estimate-v1" in js
    assert "Fysisk build kan ikke annulleres sikkert" in js
    assert 'failures.push("Persisted jobs")' in js
    assert 'failures.push("Operator-kørsler")' in js
    assert "setTimeout(() => void refresh" in js
