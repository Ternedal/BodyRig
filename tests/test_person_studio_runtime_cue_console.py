from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
MODELS = (ROOT / "bodyrig" / "models.py").read_text(encoding="utf-8")
API = (ROOT / "bodyrig" / "motor_v3_api.py").read_text(encoding="utf-8")

def test_runtime_cue_console_exposes_only_bounded_semantic_fields() -> None:
    for token in ("operatorCueGaze", "operatorCueLocomotion", "operatorCueGesture", "operatorCuePosture", "operatorCueEmotion", "operatorCueEnergy", "operatorCueIntensity", "operatorCueEffort"):
        assert token in HTML
    assert 'type: "modelrig-body-cue"' in JS
    assert 'version: 2' in JS
    assert 'body_id: activeRuntimeBodyId' in JS
    assert 'await api("/api/v2/runtime/cue"' in JS

def test_runtime_cue_console_reuses_strict_bodycue_v2_contract() -> None:
    assert 'model_config = ConfigDict(extra="forbid")' in MODELS
    assert 'class BodyCueV2(BaseModel):' in MODELS
    assert 'effort: float | None = Field(default=None, ge=0.0, le=1.0' in MODELS
    assert '@router.post("/api/v2/runtime/cue")' in API

def test_runtime_cue_console_has_no_raw_or_release_authority() -> None:
    section = JS.split("async function sendRuntimeCue", 1)[1].split("function renderService", 1)[0]
    assert "JSON.parse" not in section
    assert "production" not in section.lower()
    assert "review" not in section.lower()
    assert "activatePersonRevision" not in section
