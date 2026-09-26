from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "personality_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "personality_control_strip.css").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "bodyrig" / "ui" / "personality_workspace.js").read_text(encoding="utf-8")


def test_personality_tab_has_control_strip() -> None:
    for token in (
        'id="personalityControlStrip"',
        'id="personalityControlDraft"',
        'id="personalityControlLab"',
        'id="personalityControlActive"',
        'id="personalityControlNext"',
    ):
        assert token in HTML
    assert '<script src="/ui/personality_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/personality_control_strip.css">' in HTML


def test_personality_control_strip_consumes_structured_state_only() -> None:
    for token in (
        'root.dataset.stateVersion !== "1"',
        "data-candidate-count",
        "data-active-state",
        "data-active-label",
        "data-lab-state",
        "data-lab-mode",
        "data-lab-label",
        "data-lab-person-id",
    ):
        assert token in JS

    assert "function structuredState()" in JS
    assert "function text(id)" not in JS
    assert 'querySelectorAll(".revision-item")' not in JS
    assert "personalityWorkspaceStatus" not in JS
    assert "personalityActive" not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_personality_control_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert '.tab[data-tab="assemble"]' in JS
    assert "position:sticky" in CSS


def test_person_app_publishes_candidate_and_active_personality_state() -> None:
    assert "function publishPersonalityControlState()" in APP
    assert 'root.dataset.stateVersion = "1";' in APP
    assert "root.dataset.personId = personId;" in APP
    assert "root.dataset.candidateCount = String(candidates.length);" in APP
    assert 'activePersonality ? "bound" : "unbound"' in APP
    assert 'root.dataset.activeLabel = activePersonality;' in APP
    assert APP.count("publishPersonalityControlState();") >= 2


def test_personality_workspace_publishes_person_bound_lab_state() -> None:
    guided = "Guided Personality · kandidat-authoring for valgt person."
    suite = "6-scenarie audition · supplementary review-evidence for valgt person."

    assert "function publishLabState(mode, label)" in WORKSPACE
    assert 'root.dataset.stateVersion = "1";' in WORKSPACE
    assert "root.dataset.labPersonId = id;" in WORKSPACE
    assert "root.dataset.labMode = mode;" in WORKSPACE
    assert 'root.dataset.labState = id ? "ready" : "blocked";' in WORKSPACE
    assert "root.dataset.labLabel = id ? label :" in WORKSPACE
    assert guided in WORKSPACE
    assert suite in WORKSPACE
    assert "publishLabState(mode, label);" in WORKSPACE


def test_personality_strip_fails_closed_on_cross_person_or_malformed_state() -> None:
    assert 'new Set(["unknown", "unbound", "bound"])' in JS
    assert 'new Set(["checking", "ready", "blocked"])' in JS
    assert 'new Set(["guided", "suite"])' in JS
    assert "candidateCount === null" in JS
    assert 'active === "bound" && !activeLabel' in JS
    assert "labPersonId !== personId" in JS
    assert 'setChip("personalityControlDraft", "Ukendt", false);' in JS
    assert 'setChip("personalityControlLab", "Ukendt", false);' in JS
    assert 'setChip("personalityControlActive", "Ukendt", false);' in JS
    assert "Afventer struktureret Personality-state." in JS
