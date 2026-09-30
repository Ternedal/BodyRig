from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
STATE = (ROOT / "bodyrig" / "ui" / "person_state.js").read_text(encoding="utf-8")


def test_shared_person_state_loads_before_consumers() -> None:
    helper = HTML.index('<script src="/ui/person_state.js" defer></script>')
    assert helper < HTML.index('<script src="/ui/person_hud.js" defer></script>')
    assert helper < HTML.index('<script src="/ui/person_command_palette.js" defer></script>')


def test_shared_person_state_is_fail_closed_and_read_only() -> None:
    assert 'root.dataset.stateVersion !== "1"' in STATE
    assert 'new Set(["bound", "unbound", "unknown"])' in STATE
    assert 'integerDataset(root, "pipelineComplete")' in STATE
    assert 'integerDataset(root, "pipelineTotal")' in STATE
    assert "name.length > 160" in STATE
    assert "revision.length > 160" in STATE
    assert "complete > total" in STATE
    assert "!COMPONENT_STATES.has(body)" in STATE
    assert "!COMPONENT_STATES.has(voice)" in STATE
    assert "!COMPONENT_STATES.has(personality)" in STATE
    assert "Object.freeze({ name, revision, complete, total, body, voice, personality })" in STATE
    assert "window.BodyRigPersonState = Object.freeze" in STATE
    assert "fetch(" not in STATE
    assert "POST" not in STATE
    assert "/action" not in STATE


def test_person_state_consumers_do_not_duplicate_parser_authority() -> None:
    for path in ("person_hud.js", "person_command_palette.js", "person_activity_drawer.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigPersonState?.read()" in text
        assert "COMPONENT_STATES" not in text
        assert "dataset.personName" not in text

    for path in ("person_hud.js", "person_command_palette.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "integerDataset" not in text
