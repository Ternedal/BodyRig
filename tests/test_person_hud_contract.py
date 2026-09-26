from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_hud.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_hud.css").read_text(encoding="utf-8")


def test_person_studio_has_global_hud() -> None:
    for token in (
        'id="personHud"',
        'id="personHudName"',
        'id="personHudMeterFill"',
        'id="personHudBody"',
        'id="personHudVoice"',
        'id="personHudPersonality"',
        'id="personHudAttention"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_hud.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_hud.css">' in HTML


def test_hud_reuses_structured_rendered_state_without_new_authority() -> None:
    for token in (
        "personHud",
        "pipelineComplete",
        "pipelineTotal",
        "bodyState",
        "voiceState",
        "personalityState",
        "operatorAttentionBadge",
        "activeCount",
        "unseenCount",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert '.tab[data-tab="' in JS


def test_hud_has_control_room_visual_treatment() -> None:
    assert "position:sticky" in CSS
    assert "backdrop-filter:blur" in CSS
    assert "linear-gradient" in CSS
    assert "box-shadow" in CSS


def test_hud_attention_opens_live_activity_before_falling_back_to_drift() -> None:
    assert 'button.id === "personHudAttention"' in JS
    assert "attentionState().active > 0" in JS
    assert '$(\"personActivityToggle\").click()' in JS
    assert "return;" in JS
    assert '.tab[data-tab="' in JS
    assert "fetch(" not in JS
