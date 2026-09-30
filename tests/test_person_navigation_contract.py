from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
NAV = (ROOT / "bodyrig" / "ui" / "person_navigation.js").read_text(encoding="utf-8")


def test_shared_navigation_helper_is_loaded_before_consumers() -> None:
    helper = HTML.index('<script src="/ui/person_navigation.js" defer></script>')
    for script in (
        "/ui/person_overview_cockpit.js",
        "/ui/person_hud.js",
        "/ui/person_mission_control.js",
        "/ui/body_control_strip.js",
        "/ui/voice_control_strip.js",
        "/ui/assembly_control_strip.js",
        "/ui/operations_control_strip.js",
        "/ui/personality_control_strip.js",
        "/ui/overview_control_strip.js",
        "/ui/history_control_strip.js",
        "/ui/person_activity_drawer.js",
        "/ui/operator_control_plane.js",
        "/ui/personality_workspace.js",
        "/ui/person_command_palette.js",
    ):
        assert helper < HTML.index(f'<script src="{script}" defer></script>')


def test_shared_navigation_owns_fidelity_focus_behavior() -> None:
    assert "window.BodyRigPersonNavigation = Object.freeze" in NAV
    assert "focusFidelityCenter" in NAV
    assert "highFidelityContinuationCard" in NAV
    assert '"(prefers-reduced-motion: reduce)"' in NAV
    assert 'function focusElement(target, { block = "start" } = {})' in NAV
    assert 'target.scrollIntoView({ block, behavior: reduced ? "auto" : "smooth" })' in NAV
    assert 'target.classList.add("activity-focus")' in NAV
    assert 'target.classList.remove("activity-focus")' in NAV


def test_fidelity_navigation_consumers_reuse_shared_helper() -> None:
    for path in (
        "person_overview_cockpit.js",
        "person_hud.js",
        "person_mission_control.js",
        "body_control_strip.js",
        "voice_control_strip.js",
        "assembly_control_strip.js",
        "operations_control_strip.js",
        "personality_control_strip.js",
        "overview_control_strip.js",
        "history_control_strip.js",
        "person_activity_drawer.js",
        "operator_control_plane.js",
        "personality_workspace.js",
        "person_command_palette.js",
    ):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigPersonNavigation" in text
        assert "scrollIntoView" not in text
