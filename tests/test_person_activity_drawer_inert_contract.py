from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")

def test_closed_activity_drawer_is_inert_and_unfocusable() -> None:
    assert 'id="personActivityDrawer"' in HTML
    assert 'aria-hidden="true" inert' in HTML
    assert 'if (drawer) drawer.inert = !open;' in JS
    assert 'drawer?.setAttribute("aria-hidden", String(!open));' in JS
