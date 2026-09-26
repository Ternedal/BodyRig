from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")

def test_drift_exposes_read_only_motor_state_v3_monitor() -> None:
    assert 'id="operator-motor-badge"' in HTML
    assert 'id="operator-motor-signals"' in HTML
    assert 'readApi("/api/v3/runtime/motor-state")' in JS
    assert 'value.type === "bodyrig-motor-state"' in JS
    assert 'value.version === 3' in JS
    assert 'renderMotorState(motorState);' in JS

def test_motor_monitor_does_not_create_mutation_authority() -> None:
    motor_section = JS.split("function renderMotorState", 1)[1].split("async function refresh", 1)[0]
    assert "fetch(" not in motor_section
    assert "POST" not in motor_section
    assert "/api/v2/runtime/cue" not in JS

def test_motor_monitor_does_not_render_raw_embodiment_evidence() -> None:
    motor_section = JS.split("function renderMotorState", 1)[1].split("async function refresh", 1)[0]
    assert "embodiment" not in motor_section
    assert ".observed" not in motor_section
