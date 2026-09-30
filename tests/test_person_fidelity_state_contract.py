from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
STATE = (ROOT / "bodyrig" / "ui" / "person_fidelity_state.js").read_text(encoding="utf-8")


def test_shared_fidelity_state_helper_loads_before_consumers() -> None:
    helper = HTML.index('<script src="/ui/person_fidelity_state.js" defer></script>')
    for script in (
        "/ui/person_hud.js",
        "/ui/person_topology.js",
        "/ui/body_control_strip.js",
    ):
        assert helper < HTML.index(f'<script src="{script}" defer></script>')


def test_shared_fidelity_state_is_fail_closed_and_read_only() -> None:
    assert 'root.dataset.stateVersion !== "1"' in STATE
    assert 'new Set(["ready", "blocked", "checking", "unknown"])' in STATE
    assert 'new Set(["ready", "required", "blocked", "checking", "unknown"])' in STATE
    assert "label.length > 240" in STATE
    assert 'value?.state === "blocked" || value?.review === "required"' in STATE
    assert "Object.freeze({ state, review, label })" in STATE
    assert "fetch(" not in STATE
    assert "POST" not in STATE
    assert "/action" not in STATE


def test_fidelity_consumers_do_not_duplicate_state_parser() -> None:
    for path in ("person_hud.js", "person_topology.js", "body_control_strip.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigFidelityState?.read()" in text
        assert 'new Set(["ready", "blocked", "checking", "unknown"])' not in text
        assert 'root.dataset.fidelityState' not in text
        assert 'root.dataset.fidelityReviewState' not in text

    for path in ("person_hud.js", "person_topology.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigFidelityState?.requiresAttention" in text
