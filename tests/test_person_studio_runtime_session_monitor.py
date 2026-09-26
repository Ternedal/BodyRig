from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
RUNTIME = (ROOT / "bodyrig" / "runtime.py").read_text(encoding="utf-8")

def test_drift_renders_canonical_runtime_session_state() -> None:
    assert 'id="operator-runtime-session"' in HTML
    assert 'id="operator-runtime-detail"' in HTML
    assert 'function renderRuntimeSession(value)' in JS
    assert '["Body", String(value?.active_body_id || "ingen")]' in JS
    assert '["Utterance", String(value?.utterance_id || "idle")]' in JS
    assert 'if (key === "runtime") renderRuntimeSession(value);' in JS

def test_runtime_summary_matches_runtime_state_contract() -> None:
    assert 'active_body_id: str | None' in RUNTIME
    assert 'utterance_id: str | None' in RUNTIME
    assert 'cue: dict | None' in RUNTIME
    assert 'speech: dict | None' in RUNTIME
    assert 'updated_at: float' in RUNTIME
    assert 'revision ${value.revision' not in JS
    assert 'utterance ${value.utterance_id || "idle"}' in JS

def test_runtime_session_monitor_is_read_only() -> None:
    section = JS.split("function renderRuntimeSession", 1)[1].split("function renderService", 1)[0]
    assert "fetch(" not in section
    assert 'method: "POST"' not in section
    assert "/api/v1/runtime/cue" not in section
    assert "/api/v1/runtime/speech-timing" not in section
