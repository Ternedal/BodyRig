from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "history_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "history_control_strip.css").read_text(encoding="utf-8")

def test_history_tab_has_control_strip() -> None:
    for token in ('id="historyControlStrip"','id="historyControlActive"','id="historyControlRevisions"','id="historyControlComponents"','id="historyControlNext"'):
        assert token in HTML
    assert '<script src="/ui/history_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/history_control_strip.css">' in HTML

def test_history_strip_is_read_only_navigation() -> None:
    for token in ("historyList","personActive","bodyActive","voiceActive","personalityActive"):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert '.tab[data-tab="overview"]' in JS
    assert '.tab[data-tab="assemble"]' in JS
    assert "position:sticky" in CSS
