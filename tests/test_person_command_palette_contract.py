from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_command_palette.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_command_palette.css").read_text(encoding="utf-8")


def test_person_studio_has_command_palette() -> None:
    for token in (
        'id="personCommandPalette"',
        'id="personCommandPaletteBackdrop"',
        'id="personCommandPaletteInput"',
        'id="personCommandPaletteResults"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_command_palette.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_command_palette.css">' in HTML


def test_command_palette_routes_to_existing_ui_only() -> None:
    for token in (
        '"overview"',
        '"body"',
        '"voice"',
        '"personality"',
        '"assemble"',
        '"history"',
        '"operations"',
        "personActivityToggle",
        "newPersonButton",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_command_palette_has_keyboard_navigation() -> None:
    for token in ('key.toLowerCase() === "k"', '"ArrowDown"', '"ArrowUp"', '"Enter"', '"Escape"'):
        assert token in JS
    assert "role=\"dialog\"" in HTML
    assert "aria-modal=\"true\"" in HTML
    assert "backdrop-filter:blur" in CSS
