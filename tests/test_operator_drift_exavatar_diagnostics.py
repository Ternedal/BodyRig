from pathlib import Path


def test_drift_exavatar_diagnostics_render_existing_read_only_evidence() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    assert 'id="operator-exavatar-diagnostics"' in html
    assert "ExAvatar live diagnostics" in html
    assert "function renderExavatarDiagnostics(value)" in js
    assert "exavatar.active_processes" in js
    assert "exavatar.latest_log" in js
    assert "latest.tail" in js
    assert "activity.reason" in js
    assert "Workspace-bundne processer" in js
    assert "Seneste bounded log-tail" in js
    assert "textContent = active.join" in js
    assert "pre.textContent = tail.slice(-6000)" in js
    assert ".operator-exavatar-log-tail" in css
    assert ".operator-exavatar-processes" in css


def test_exavatar_diagnostics_are_bounded_before_browser_rendering() -> None:
    core = Path("bodyrig/photoreal_control_plane_ui.py").read_text(encoding="utf-8")

    assert 'active.append({' in core
    assert '"display": f"{proc.name} {command}"[:1200]' in core
    assert '"tail": "\\n".join(text.splitlines()[-20:])[-6000:]' in core
    assert 'value["active_processes"] = filtered' in core
    assert "if len(filtered) >= 20:" in core


def test_drift_exavatar_diagnostics_add_no_execution_authority() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    api = Path("bodyrig/photoreal_control_plane_ui_api.py").read_text(encoding="utf-8")

    start = js.index("function renderExavatarDiagnostics")
    end = js.index("function renderPhotoreal", start)
    block = js[start:end]

    assert "fetch(" not in block
    assert "api(" not in block
    assert "POST" not in block
    assert "kill" not in block.lower()
    assert "terminate" not in block.lower()
    assert "/diagnostics/action" not in api
