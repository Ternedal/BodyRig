from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_mission_control.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_mission_control.css").read_text(encoding="utf-8")
PALETTE = (ROOT / "bodyrig" / "ui" / "person_command_palette.js").read_text(encoding="utf-8")


def test_person_studio_has_global_mission_control() -> None:
    for token in (
        'id="personMissionControl"',
        'id="personMissionTitle"',
        'id="personMissionDetail"',
        'id="personMissionAction"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_mission_control.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_mission_control.css">' in HTML


def test_mission_control_reuses_existing_pipeline_prioritization() -> None:
    assert "overviewCockpitAttention" in JS
    assert "overviewCockpitNext" in JS
    assert "MutationObserver" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_mission_control_is_exposed_in_command_palette() -> None:
    assert 'id: "mission"' in PALETTE
    assert "personMissionAction" in PALETTE


def test_mission_control_has_attention_visual_state() -> None:
    assert ".person-mission-control.attention" in CSS
    assert "person-mission-pulse" in CSS
    assert "text-overflow:ellipsis" in CSS
