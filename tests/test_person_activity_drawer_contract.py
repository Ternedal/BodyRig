from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")


def test_person_studio_has_global_live_activity_drawer() -> None:
    for token in (
        'id="personActivityDrawer"',
        'id="personActivityToggle"',
        'id="personActivityAttention"',
        'id="personActivityJobs"',
        'id="personActivityLaunches"',
        'id="personActivityPhotoreal"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_activity_drawer.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_activity_drawer.css">' in HTML


def test_activity_drawer_reuses_rendered_drift_state_only() -> None:
    for token in (
        "operatorAttentionItems",
        "operatorJobs",
        "operatorLaunches",
        "operator-photoreal-badge",
        "operator-photoreal-summary",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert "MutationObserver" in JS


def test_activity_drawer_is_global_control_room_ui() -> None:
    assert "position:fixed" in CSS
    assert "backdrop-filter:blur" in CSS
    assert ".person-activity-drawer.open" in CSS
    assert "prefers-reduced-motion" in CSS
