from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_focus_mode.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_focus_mode.css").read_text(encoding="utf-8")
PALETTE = (ROOT / "bodyrig" / "ui" / "person_command_palette.js").read_text(encoding="utf-8")


def test_person_studio_has_focus_mode_control() -> None:
    assert 'id="personFocusToggle"' in HTML
    assert 'id="personFocusToggleText"' in HTML
    assert '<script src="/ui/person_focus_mode.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_focus_mode.css">' in HTML


def test_focus_mode_is_presentation_only() -> None:
    assert "localStorage" in JS
    assert "person-focus-mode" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert "Shift" not in JS or 'event.key.toLowerCase() === "f"' in JS


def test_focus_mode_collapses_sidebar_and_expands_workspace() -> None:
    assert "body.person-focus-mode .sidebar" in CSS
    assert "body.person-focus-mode .app-shell" in CSS
    assert "grid-template-columns:0 minmax(0,1fr)" in CSS
    assert "max-width:none" in CSS


def test_command_palette_can_toggle_focus_mode() -> None:
    assert 'id: "focus"' in PALETTE
    assert "personFocusToggle" in PALETTE
