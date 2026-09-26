from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "bodyrig" / "ui" / "person_command_palette.css").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_command_palette.js").read_text(encoding="utf-8")

def test_command_palette_locks_background_scroll() -> None:
    assert "body.person-command-open{overflow:hidden}" in CSS
    assert 'document.body.classList.add("person-command-open")' in JS
    assert 'document.body.classList.remove("person-command-open")' in JS
