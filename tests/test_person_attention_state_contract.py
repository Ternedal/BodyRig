from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
STATE = (ROOT / "bodyrig" / "ui" / "person_attention_state.js").read_text(encoding="utf-8")


def test_shared_attention_state_loads_before_consumers() -> None:
    helper = HTML.index('<script src="/ui/person_attention_state.js" defer></script>')
    for script in (
        "/ui/person_hud.js",
        "/ui/person_command_palette.js",
        "/ui/person_activity_drawer.js",
    ):
        assert helper < HTML.index(f'<script src="{script}" defer></script>')


def test_shared_attention_state_is_fail_closed_and_read_only() -> None:
    assert 'badge.dataset.stateVersion !== "1"' in STATE
    assert 'integerDataset(badge, "activeCount")' in STATE
    assert 'integerDataset(badge, "unseenCount")' in STATE
    assert "Number.isSafeInteger(value) && value >= 0" in STATE
    assert "unseen > active" in STATE
    assert "Object.freeze({ active: 0, unseen: 0 })" in STATE
    assert "Object.freeze({ active, unseen })" in STATE
    assert "window.BodyRigAttentionState = Object.freeze" in STATE
    assert "fetch(" not in STATE
    assert "POST" not in STATE
    assert "/action" not in STATE


def test_attention_consumers_do_not_duplicate_badge_parser() -> None:
    for path in ("person_hud.js", "person_command_palette.js", "person_activity_drawer.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigAttentionState?.read()" in text
        assert "dataset?.activeCount" not in text
        assert 'integerDataset(badge, "activeCount")' not in text
        assert 'integerDataset(badge, "unseenCount")' not in text
