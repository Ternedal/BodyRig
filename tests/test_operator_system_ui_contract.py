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
    assert "/api/v1/operator/launches?limit=12" in js
    assert "renderLaunches" in js
    assert "window.confirm" in js
    assert "mutates_environment" in js
    assert "ExAvatar" in js and "idle" in js
    assert "renderSystemDetail" in js
    assert "Runtime receipt" in js
    assert "ADB-enheder" in js
    assert "command" not in js.split("JSON.stringify({ action })", 1)[0].split("runSystemAction", 1)[-1]
