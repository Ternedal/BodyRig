from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")
MODELS = (ROOT / "bodyrig" / "models.py").read_text(encoding="utf-8")

def test_runtime_speech_console_binds_to_active_utterance() -> None:
    assert 'id="operatorSpeechSend"' in HTML
    assert 'activeRuntimeUtteranceId' in JS
    assert 'utterance_id: activeRuntimeUtteranceId' in JS
    assert 'await api("/api/v1/runtime/speech-timing"' in JS

def test_runtime_speech_console_reuses_strict_speech_timing_contract() -> None:
    assert 'class SpeechTiming(BaseModel):' in MODELS
    assert 'model_config = ConfigDict(extra="forbid")' in MODELS
    assert 'state: Literal["start", "update", "stop"]' in MODELS
    assert 'elapsed_ms: int = Field(default=0, ge=0, le=3_600_000)' in MODELS
    assert 'amplitude: float | None = Field(default=None, ge=0.0, le=1.0' in MODELS
    assert '@app.post("/api/v1/runtime/speech-timing")' in APP

def test_runtime_speech_console_has_no_release_or_raw_authority() -> None:
    section = JS.split("async function sendRuntimeSpeechTiming", 1)[1].split("function renderService", 1)[0]
    assert "JSON.parse" not in section
    assert "production" not in section.lower()
    assert "review" not in section.lower()
    assert "activatePersonRevision" not in section
