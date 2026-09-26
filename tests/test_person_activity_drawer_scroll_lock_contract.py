from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")

def test_activity_drawer_locks_background_scroll() -> None:
    assert "body.person-activity-open{overflow:hidden}" in CSS
    assert 'document.body.classList.toggle("person-activity-open", open)' in JS
    assert 'if (event.key === "Escape" && open) setOpen(false);' in JS
