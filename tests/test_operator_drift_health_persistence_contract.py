from pathlib import Path


def _js() -> str:
    return Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_drift_health_observations_persist_only_timestamp_and_transition_evidence() -> None:
    js = _js()

    assert 'const SERVICE_OBSERVATION_STORAGE_KEY = "bodyrig-drift-service-observations-v2";' in js
    assert 'const SERVICE_OBSERVATION_LEGACY_STORAGE_KEY = "bodyrig-drift-service-observations-v1";' in js
    assert "const SERVICE_OBSERVATION_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;" in js
    assert "const SERVICE_TRANSITION_LIMIT = 120;" in js
    assert 'new Set(["green", "blocked", "offline"])' in js
    assert "function restoreServiceObservations()" in js
    assert "function persistServiceObservations()" in js
    assert "function normalizedServiceTransitions" in js
    assert "function recordServiceTransition" in js
    assert 'payload.format !== "bodyrig-drift-service-observations"' in js
    assert "payload.version !== 2" in js
    assert "payload.version !== 1" in js
    assert "last_attempt_ms" in js
    assert "last_confirmed_ms" in js
    assert "last_green_ms" in js
    assert "transitions: serviceTransitions" in js
    assert "window.localStorage.getItem(SERVICE_OBSERVATION_STORAGE_KEY)" in js
    assert "window.localStorage.getItem(SERVICE_OBSERVATION_LEGACY_STORAGE_KEY)" in js
    assert "window.localStorage.setItem(" in js
    assert "JSON.stringify(payload)" in js

    persistence = js[
        js.index("function persistServiceObservations()"):
        js.index("function panel()")
    ]
    for forbidden in (
        "physical_build_reason",
        "active_body_id",
        "performer_read",
        "bodyrig_revision",
        "wsl_cuda",
        "access_token",
        "password",
        "error:",
        "blockers:",
        "value:",
    ):
        assert forbidden not in persistence


def test_persisted_health_history_has_ttl_bounded_transitions_and_rejects_invalid_data() -> None:
    js = _js()

    assert "function persistedObservationStamp(value, now = Date.now())" in js
    assert "!Number.isFinite(value) || value <= 0" in js
    assert "value > now + 60000" in js
    assert "now - value > SERVICE_OBSERVATION_RETENTION_MS" in js
    assert "new Set(SERVICES.map(([key]) => key))" in js
    assert "values.slice(-SERVICE_TRANSITION_LIMIT)" in js
    assert "SERVICE_TRANSITION_STATES.has(state)" in js
    assert "result.slice(-SERVICE_TRANSITION_LIMIT)" in js
    assert "serviceTransitions = version === 2" in js
    assert "restoreServiceObservations();" in js


def test_service_transition_history_records_only_real_state_changes() -> None:
    js = _js()

    transition = js[
        js.index("function recordServiceTransition"):
        js.index("function healthTimelineStateLabel")
    ]
    assert "previousState === state" in transition
    assert "serviceTransitions.push({ service: key, state, observed_ms: stamp })" in transition
    assert "serviceTransitions.slice(-SERVICE_TRANSITION_LIMIT)" in transition

    observation = js[
        js.index("function recordServiceObservation"):
        js.index("function serviceResultFresh")
    ]
    assert 'result?.ok !== true' in observation
    assert '"offline"' in observation
    assert 'healthy ? "green" : "blocked"' in observation
    assert "recordServiceTransition" in observation


def test_persisted_history_never_becomes_current_health_authority() -> None:
    js = _js()

    freshness = js[
        js.index("function serviceResultFresh"):
        js.index("function ageLabel")
    ]
    assert "result?.observed_ms" in freshness
    assert "last_confirmed_ms" not in freshness
    assert "last_green_ms" not in freshness
    assert "serviceTransitions" not in freshness
    assert "age <= SERVICE_STALE_MS" in freshness

    assert "persistServiceObservations();" in js
    assert "sidst grøn" in js
    assert "storage failure never changes authority" in js


def test_health_timeline_is_render_only_browser_context() -> None:
    js = _js()
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    assert 'id="operatorHealthTimelineStatus"' in html
    assert 'id="operatorHealthTimeline"' in html
    assert "Browser-lokal observationshistorik" in html
    assert "function renderHealthTimeline()" in js
    assert "SERVICE_TRANSITION_RENDER_LIMIT = 40" in js
    assert "healthTimelineStateLabel" in js
    assert 'toLocaleString("da-DK")' in js
    assert "renderHealthTimeline();" in js
    assert ".operator-health-timeline" in css
    assert ".operator-health-event" in css

    renderer = js[
        js.index("function renderHealthTimeline"):
        js.index("function panel()")
    ]
    for forbidden in (
        "fetch(",
        "api(",
        "POST",
        "next_command",
        "production_activation",
        "window.confirm",
    ):
        assert forbidden not in renderer
