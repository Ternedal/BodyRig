from pathlib import Path


def _js() -> str:
    return Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_drift_health_observations_persist_only_timestamp_evidence() -> None:
    js = _js()

    assert 'const SERVICE_OBSERVATION_STORAGE_KEY = "bodyrig-drift-service-observations-v1";' in js
    assert "const SERVICE_OBSERVATION_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;" in js
    assert "function restoreServiceObservations()" in js
    assert "function persistServiceObservations()" in js
    assert 'payload.format !== "bodyrig-drift-service-observations"' in js
    assert "payload.version !== 1" in js
    assert "last_attempt_ms" in js
    assert "last_confirmed_ms" in js
    assert "last_green_ms" in js
    assert "window.localStorage.getItem(SERVICE_OBSERVATION_STORAGE_KEY)" in js
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
    ):
        assert forbidden not in persistence


def test_persisted_health_history_has_ttl_and_rejects_invalid_timestamps() -> None:
    js = _js()

    assert "function persistedObservationStamp(value, now = Date.now())" in js
    assert "!Number.isFinite(value) || value <= 0" in js
    assert "value > now + 60000" in js
    assert "now - value > SERVICE_OBSERVATION_RETENTION_MS" in js
    assert "new Set(SERVICES.map(([key]) => key))" in js
    assert "restoreServiceObservations();" in js


def test_persisted_history_never_becomes_current_health_authority() -> None:
    js = _js()

    freshness = js[
        js.index("function serviceResultFresh"):
        js.index("function ageLabel")
    ]
    assert "result?.observed_ms" in freshness
    assert "last_confirmed_ms" not in freshness
    assert "last_green_ms" not in freshness
    assert "age <= SERVICE_STALE_MS" in freshness

    assert "persistServiceObservations();" in js
    assert "sidst grøn" in js
    assert "storage failure never changes authority" in js
