from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
MODELS = (ROOT / "bodyrig" / "models.py").read_text(encoding="utf-8")

def test_runtime_cue_console_covers_remaining_bodycue_v2_fields() -> None:
    assert 'id="operatorCueGazeObject"' in HTML
    assert 'id="operatorCueDuration"' in HTML
    assert 'payload.gaze = "object:" + gazeObject' in JS
    assert 'payload.duration_ms = duration' in JS
    assert '"duration_ms"' in JS

def test_gaze_object_and_duration_match_backend_contract() -> None:
    assert 'if (value.startswith("object:")' in MODELS
    assert 'len(value[7:]) <= 120' in MODELS
    assert 'duration_ms: int | None = Field(default=None, ge=0, le=120_000)' in MODELS
    assert 'speechNumber("operatorCueDuration", 0, 120000, true)' in JS

def test_cue_console_refuses_ambiguous_gaze_selection() -> None:
    section = JS.split("async function sendRuntimeCue", 1)[1].split("function speechNumber", 1)[0]
    assert 'if (gaze && gazeObject) throw new Error("Vælg enten standard-gaze eller gaze object.");' in section
