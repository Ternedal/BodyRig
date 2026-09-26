from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")

def test_voice_test_bench_is_revision_bound() -> None:
    assert 'id="voiceTestRevision"' in HTML
    assert 'id="voiceTestText"' in HTML
    assert 'id="voiceTestAudio"' in HTML
    assert 'body: JSON.stringify({ revision, text: textValue })' in JS
    assert '/voice/synthesize' in JS

def test_voice_test_bench_reuses_canonical_hash_validated_backend() -> None:
    assert '@app.post("/api/v1/people/{person_id}/voice/synthesize")' in APP
    assert 'item = _revision(profile, "voice", request.revision)' in APP
    assert '_voice_bytes_match(item, client)' in APP
    assert 'client.synthesize(str(item["voice_package"]), request.text)' in APP

def test_voice_test_bench_cleans_blob_urls_and_does_not_activate() -> None:
    section = JS.split("function resetVoiceTest", 1)[1].split("function renderSelected", 1)[0]
    assert "URL.revokeObjectURL" in section
    assert "URL.createObjectURL" in section
    assert "activatePersonRevision" not in section
    assert "/revisions/" not in section


def test_voice_test_bench_discards_stale_person_results() -> None:
    section = JS.split("async function runVoiceTest", 1)[1].split("function renderSelected", 1)[0]
    assert "const requestSerial = state.voiceTestSerial;" in section
    assert "const personId = state.selected.person_id;" in section
    assert "requestSerial !== state.voiceTestSerial" in section
    assert "state.selected?.person_id !== personId" in section
    assert '$("voiceTestRevision")?.value !== revision' in section
    assert "state.voiceTestSerial += 1;" in JS.split("function resetVoiceTest", 1)[1].split("function populateVoiceTestRevisions", 1)[0]
