from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")

def test_saved_voice_candidates_have_revision_bound_preview() -> None:
    assert 'if (kind === "voice")' in JS
    assert 'audio.preload = "none";' in JS
    assert '/voice/preview?revision=${encodeURIComponent(item.revision_id)}' in JS
    assert 'audio.setAttribute("aria-label", `Preview ${item.revision_id}`);' in JS

def test_voice_preview_route_revalidates_saved_package_bytes() -> None:
    assert '@app.get("/api/v1/people/{person_id}/voice/preview")' in APP
    assert 'item = _revision(profile, "voice", revision)' in APP
    assert '_voice_bytes_match(item, client)' in APP
    assert 'client.preview(str(item["voice_package"]))' in APP
