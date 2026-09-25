from pathlib import Path


def _js() -> str:
    return Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_drift_health_reads_are_timeout_bounded_and_no_store() -> None:
    js = _js()

    assert "const SERVICE_READ_TIMEOUT_MS = 7000;" in js
    assert "const SERVICE_STALE_MS = 25000;" in js
    assert "new AbortController()" in js
    assert "setTimeout(() => controller.abort(), timeoutMs)" in js
    assert 'cache: "no-store"' in js
    assert "monitor read timeout efter" in js
    assert "clearTimeout(timeout)" in js
    assert "await readApi(url)" in js


def test_drift_health_green_requires_expected_readiness_evidence() -> None:
    js = _js()

    assert 'value.ok !== true' in js
    assert 'value.physical_build_ready !== true' in js
    assert 'value.performer_read !== true' in js
    assert 'value.service !== "modelrig-server"' in js
    assert 'value.service !== "voicerig"' in js
    assert 'Object.prototype.hasOwnProperty.call(value, "updated_at")' in js
    assert 'typeof value.updated_at !== "number"' in js
    assert '!Number.isFinite(value.updated_at)' in js
    assert 'value.updated_at <= 0' in js
    assert 'value.wsl_cuda?.ready !== true' in js
    assert 'value.powershell_7 !== true' in js
    assert "return serviceBlockers(key, value).length === 0;" in js


def test_drift_health_tracks_last_confirmed_and_rejects_stale_evidence() -> None:
    js = _js()

    assert "const serviceObservations = new Map();" in js
    assert "last_confirmed_ms" in js
    assert "last_green_ms" in js
    assert "serviceResultFresh" in js
    assert "age <= SERVICE_STALE_MS" in js
    assert "sidst bekræftet" in js
    assert "intet bekræftet svar" in js
    assert "STALE health-evidence" in js
    assert 'setBadge(badgeId, healthy, healthy ? "Klar" : (fresh ? "Blokeret" : "Stale"))' in js


def test_top_summary_treats_timeout_stale_and_blocked_service_as_attention() -> None:
    js = _js()

    assert "item.ok === false" in js
    assert "!serviceResultFresh(item)" in js
    assert "!serviceHealthy(item.key, item.value)" in js
    assert 'attention.join(", ")' in js


def test_all_drift_monitoring_gets_use_the_bounded_read_path() -> None:
    js = _js()

    assert '(await readApi("/api/v1/jobs")).value' in js
    assert 'await readApi(`/api/v1/jobs/${encodeURIComponent(jobId)}`)' in js
    assert '(await readApi("/api/v1/operator/launches?limit=12")).value' in js
    assert 'await readApi(`/api/v1/people/${encodeURIComponent(personId)}`)' in js
    assert '/body/photoreal-control-plane`,' in js
    assert 'if (fresh) renderSystemActions(value);' in js
    assert 'document.getElementById("operator-system-actions")?.replaceChildren();' in js


def test_drift_clears_stale_green_badges_before_refresh_completes() -> None:
    js = _js()

    assert "function markServicesChecking()" in js
    assert 'setBadge(`operator-${key}-badge`, false, "Kontrollerer")' in js
    assert 'document.getElementById("operator-system-actions")?.replaceChildren();' in js
    refresh = js[js.index("async function refresh"):js.index("function schedule")]
    assert refresh.index("markServicesChecking();") < refresh.index("Promise.all(")
