from pathlib import Path


def test_operator_system_readiness_is_read_only_and_pinned() -> None:
    source = Path("bodyrig/operator_system_ui_api.py").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert "/api/v1/operator/system-readiness" in source
    assert "/api/v1/operator/system-readiness/action" in source
    assert "/api/v1/operator/launches" in source
    assert "operator_system_ui_router" in app
    assert "app.include_router(operator_system_ui_router)" in app
    assert "Ubuntu-22.04" in source
    assert "/opt/bodyrig-exavatar/bin/python" in source
    assert "/opt/bodyrig-photoreal/bin/python" in source
    assert "required_version" in source and '"12.4"' in source
    assert "renderer-contract.json" in source
    assert "SDK" in source and "platform-tools" in source and "adb.exe" in source
    assert "Get-Command adb" not in source
    assert "read_only" in source
    assert "production_activation" in source
    assert "run-rig-preflight" in source
    assert "run-rig-preflight-quest" in source
    assert "run-exavatar-readiness-doctor" in source
    assert "setup-exavatar-public-code" in source
    assert "setup-exavatar-runtime" in source
    assert "resume-exavatar-runtime" in source
    assert "launch_canonical_operator(" in source
    assert "high-fidelity-rig-preflight.ps1" in source
    assert "RequireQuestConnected" in source
    assert "active_exavatar_processes" in source
    assert '"available": False' in source
    assert '"available": True' in source
    assert 'gpu_ready' in source and 'cuda_ready' in source
    assert "ExAvatar er aktiv; miljøændrende setup er låst" in source
    assert "setup-photoreal-exavatar-public-code.ps1" in source
    assert "setup-photoreal-exavatar-wsl.ps1" in source
    assert " -Resume" in source
    assert "-Force" not in source
    assert "/api/v1/operator/system-readiness" in js
    assert "/api/v1/operator/system-readiness/action" in js
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    assert "operator-system-actions" in html
    assert "operatorLaunches" in html
    assert "operatorLaunchesStatus" in html
    assert "operator-system-detail" in html
    assert "log_tail" in source
    assert "_pid_running" in source
    assert "_operator_launch_receipt" in source
    assert "_operator_launch_result" in source
    assert "_operator_launch_heartbeat" in source
    assert "heartbeat.json" in source
    assert "heartbeat is not None and _pid_running(pid)" in source
    assert "result.json" in source
    assert '"state": state' in source
    assert '"exit_code": terminal.get("exit_code")' in source
    assert '"finished_utc": terminal.get("finished_utc")' in source
    assert '"duration_seconds": terminal.get("duration_seconds")' in source
    assert '"process_role": process_role or None' in source
    assert 'terminal.get("child_pid")' in source
    assert 'heartbeat.get("child_pid")' in source
    assert "request_sha256=request_sha256 or None" in source
    assert "/api/v1/operator/launches?limit=50" in js
    assert "renderLaunches" in js
    assert "window.confirm" in js
    assert "mutates_environment" in js
    assert "ExAvatar" in js and "idle" in js
    assert "renderSystemDetail" in js
    assert "_system_readiness_blockers" in source
    assert '"blockers": blockers' in source
    assert '"ready": not blockers' in source
    assert "renderServiceWhy" in js
    assert "Hvorfor?" in js
    assert 'id="operator-system-why"' in html
    assert "Runtime receipt" in js
    assert "ADB-enheder" in js
    assert '"succeeded"' in js
    assert '"failed"' in js
    assert '"PASS"' in js
    assert '"FEJL"' in js
    assert "exit_code" in js
    assert "duration_seconds" in js
    assert "finished_utc" in js
    assert "restart-safe-supervisor" in js
    assert "Supervisor PID" in js
    assert "PowerShell PID" in js
    assert "heartbeat_fresh" in js
    assert "heartbeat mangler/stale" in js
    assert "integrity_valid" in source
    assert "integrity_error" in source
    assert "INTEGRITETSFEJL" in js
    assert "Launch receipt afvist" in js
    assert "command" not in js.split("JSON.stringify({ action })", 1)[0].split("runSystemAction", 1)[-1]


def test_drift_operator_launch_history_filters_and_evidence_are_read_only() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    for control in (
        "operatorLaunchPersonFilter",
        "operatorLaunchCategoryFilter",
        "operatorLaunchStateFilter",
        "operatorLaunchSearch",
    ):
        assert f'id="{control}"' in html

    assert "function filteredLaunches(launches)" in js
    assert 'personFilter === "current"' in js
    assert "!selectedPerson" in js
    assert "function launchEvidenceLines(launch)" in js
    assert "function appendLaunchEvidence(meta, launch)" in js
    assert "function appendLaunchLog(meta, launch)" in js
    assert "async function openLaunchPerson(launch)" in js
    assert "lastLaunchesPayload" in js
    assert "renderLaunches(lastLaunchesPayload)" in js
    assert "visibleLaunches = filtered.slice(0, 30)" in js
    assert "/api/v1/operator/launches?limit=50" in js
    assert "JSON.stringify(launch)" not in js
    assert "Evidence / detaljer" in js
    assert "Seneste operator-log" in js
    assert "Åbn Krop" in js
    assert ".operator-launch-filters" in css
    assert ".operator-launch-evidence-body" in css

    renderer = js[js.index("function renderLaunches"):js.index("function renderJobs")]
    assert "/api/v1/operator/system-readiness/action" not in renderer
    assert "launch_canonical_operator" not in renderer
