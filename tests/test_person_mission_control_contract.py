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


def test_mission_control_reuses_structured_pipeline_prioritization() -> None:
    assert 'root.dataset.stateVersion !== "1"' in JS
    assert "MISSION_KINDS" in JS
    assert "TARGET_TABS" in JS
    assert "missionKind" in JS
    assert "missionDetail" in JS
    assert "missionTargetTab" in JS
    assert "missionActionLabel" in JS
    assert "MutationObserver" in JS
    assert "overviewCockpitAttention" not in JS
    assert "overviewCockpitNext" not in JS
    assert "inferredTab" not in JS
    assert "firstClickable" not in JS
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

def test_overview_publishes_structured_mission_control_state() -> None:
    overview = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.js").read_text(encoding="utf-8")
    assert "function publishMissionControlState(action)" in overview
    assert "function publishMissionControlUnknown()" in overview
    assert 'root.dataset.missionKind = isAttention ? "attention" : "next";' in overview
    assert 'root.dataset.missionTargetTab = targetTab;' in overview
    assert "publishMissionControlState(action);" in overview
    assert "publishMissionControlUnknown();" in overview
