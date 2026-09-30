from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
STATE = (ROOT / "bodyrig" / "ui" / "person_mission_state.js").read_text(encoding="utf-8")


def test_shared_mission_state_loads_before_consumers() -> None:
    helper = HTML.index('<script src="/ui/person_mission_state.js" defer></script>')
    assert helper < HTML.index('<script src="/ui/person_mission_control.js" defer></script>')
    assert helper < HTML.index('<script src="/ui/person_command_palette.js" defer></script>')


def test_shared_mission_state_is_fail_closed_and_read_only() -> None:
    assert 'root.dataset.stateVersion !== "1"' in STATE
    assert 'new Set(["unknown", "attention", "next", "complete"])' in STATE
    assert '"overview", "body", "voice", "personality", "assemble", "history", "operations"' in STATE
    assert "title.length > 160" in STATE
    assert "detail.length > 1000" in STATE
    assert "actionLabel.length > 120" in STATE
    assert "targetSection.length > 80" in STATE
    assert 'targetSection !== "fidelity-command-center"' in STATE
    assert 'targetSection && targetTab !== "body"' in STATE
    assert "Object.freeze({ kind, title, detail, targetTab, actionLabel, targetSection })" in STATE
    assert "window.BodyRigMissionState = Object.freeze" in STATE
    assert "fetch(" not in STATE
    assert "POST" not in STATE
    assert "/action" not in STATE


def test_mission_consumers_do_not_duplicate_parser_authority() -> None:
    for path in ("person_mission_control.js", "person_command_palette.js"):
        text = (ROOT / "bodyrig" / "ui" / path).read_text(encoding="utf-8")
        assert "BodyRigMissionState?.read()" in text
        assert "MISSION_KINDS" not in text
        assert "TARGET_TABS" not in text
        assert "dataset.missionKind" not in text
