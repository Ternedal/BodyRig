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
        "/body/photoreal-control-plane",
    ):
        assert endpoint in js
    assert "/cancel" in js
    assert "Annullér" in js
    assert "serviceHealthy" in js
    assert 'value.physical_build_ready === true' in js
    assert 'value.performer_read === true' in js
    assert 'value.wsl_cuda?.ready !== true' in js
    assert 'value.powershell_7 !== true' in js
    assert 'value.service !== "modelrig-server"' in js
    assert 'value.service !== "voicerig"' in js
    assert 'attention.join(", ")' in js
    assert "physical_build_reason" in js
    assert "runtime, jobs og operator authority er grønne" in js
    assert 'new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"])' in js
    assert 'new Set(["needs_speaker", "needs_reference"])' in js
    assert "jobCanCancel" in js
    assert 'String(job?.kind || "") === "body-build" && status === "queued"' in js
    assert 'String(job?.kind || "") === "voice-build"' in js
    assert "diagnostic_tail" in js
    assert "progress_kind" in js
    assert "pipeline-phase-estimate-v1" in js
    assert "Fysisk build kan ikke annulleres sikkert" in js
    assert "jobAttention" in js
    assert "launchAttention" in js
    assert "latestByKey" in js
    assert "renderPhotoreal" in js
    assert "photorealAttention" in js
    assert 'id="operator-photoreal-badge"' in html
    assert 'id="operator-photoreal-detail"' in html
    assert "Photoreal / ExAvatar" in html
    assert "setTimeout(() => void refresh" in js
    assert "hydrateOpenVoiceJobs" in js
    assert "renderVoiceJobChoices" in js
    assert "/speaker?anchor=" in js
    assert "/reference?choice=" in js
    assert "monitoring_error" in js
    assert 'id="operatorJobPersonFilter"' in html
    assert 'id="operatorJobKindFilter"' in html
    assert 'id="operatorJobStateFilter"' in html
    assert 'id="operatorJobSearch"' in html
    assert "filteredJobs" in js
    assert "jobEvidenceLines" in js
    assert "appendJobEvidence" in js
    assert "openJobPerson" in js
    assert "SERVICE_READ_TIMEOUT_MS" in js
    assert "SERVICE_STALE_MS" in js
    assert "readApi" in js
    assert "serviceBlockers" in js
    assert "recordServiceObservation" in js
    assert "serviceResultFresh" in js
    assert "serviceObservationLabel" in js
    assert "STALE health-evidence" in js
    assert 'id="operatorLaunchPersonFilter"' in html
    assert 'id="operatorLaunchCategoryFilter"' in html
    assert 'id="operatorLaunchStateFilter"' in html
    assert 'id="operatorLaunchSearch"' in html
    assert "filteredLaunches" in js
    assert "launchEvidenceLines" in js
    assert "appendLaunchEvidence" in js
    assert "openLaunchPerson" in js
