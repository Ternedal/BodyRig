from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP = (ROOT / "bodyrig" / "ui" / "voice_control_strip.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")


def test_voice_library_readiness_is_not_inferred_from_rendered_copy() -> None:
    assert "function text(id)" not in STRIP
    assert "validerede VoiceRig-stemmer" not in STRIP
    assert "selectedVoiceLabel" not in STRIP
    assert "candidateCount()" not in STRIP
    assert "replace(/^Stemme" not in STRIP


def test_person_app_publishes_structured_voice_library_state() -> None:
    assert "function publishVoiceControlState()" in APP
    assert 'root.dataset.libraryState = state.voiceLibraryReady === true' in APP
    assert 'root.dataset.selectedState = selectedPackage ? "ready" : "none";' in APP
    assert 'root.dataset.candidateCount = String(candidates.length);' in APP
    assert 'root.dataset.activeState = activeVoice ? "bound" : "unbound";' in APP
    assert '$("voiceLibrarySelect")?.addEventListener("change", publishVoiceControlState);' in APP


def test_voice_library_status_tracks_actual_load_result() -> None:
    assert "state.voiceLibraryReady = null;" in APP
    assert "state.voiceLibraryReady = true;" in APP
    assert "state.voiceLibraryReady = false;" in APP
