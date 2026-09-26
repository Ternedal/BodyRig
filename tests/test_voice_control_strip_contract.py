from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "voice_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "voice_control_strip.css").read_text(encoding="utf-8")


def test_voice_tab_has_control_strip() -> None:
    for token in (
        'id="voiceControlStrip"',
        'id="voiceControlLibrary"',
        'id="voiceControlSelected"',
        'id="voiceControlActive"',
        'id="voiceControlNext"',
    ):
        assert token in HTML
    assert '<script src="/ui/voice_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/voice_control_strip.css">' in HTML


def test_voice_control_strip_reuses_structured_voice_state() -> None:
    for token in (
        'root.dataset.stateVersion !== "1"',
        "libraryState",
        "selectedState",
        "candidateCount",
        "activeState",
        '"data-library-state"',
        '"data-selected-state"',
        '"data-candidate-count"',
        '"data-active-state"',
    ):
        assert token in JS
    for forbidden in ("voiceLibraryStatus", "voiceRevisions", "voiceActive"):
        assert forbidden not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_voice_control_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert '.tab[data-tab="assemble"]' in JS
    assert "position:sticky" in CSS
