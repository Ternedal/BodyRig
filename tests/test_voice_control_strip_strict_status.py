from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "voice_control_strip.js").read_text(encoding="utf-8")

def test_voice_library_requires_canonical_success_status() -> None:
    assert '/^\\d+ validerede VoiceRig-stemmer\\.$/i.test(libraryStatus)' in JS
    assert '/klar|forbundet|voice|stemme/i' not in JS
