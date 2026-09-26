from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "personality_workspace.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "personality_workspace.css").read_text(encoding="utf-8")
FUTURE = (ROOT / "bodyrig" / "ui" / "person_studio_futuristic.css").read_text(encoding="utf-8")


def test_personality_tools_are_embedded_in_person_studio() -> None:
    assert 'id="personalityWorkspaceFrame"' in HTML
    assert 'id="personalityWorkspaceGuided"' in HTML
    assert 'id="personalityWorkspaceSuite"' in HTML
    assert '<script src="/ui/personality_workspace.js" defer></script>' in HTML
    assert "/ui/personality_guided.html" in JS
    assert "/ui/personality_audition_suite.html" in JS
    assert "person_id=" in JS


def test_embedded_workspace_does_not_add_activation_authority() -> None:
    assert 'method: "POST"' not in JS
    assert "/action" not in JS
    assert "fetch(" not in JS
    assert "window.open" in JS


def test_person_studio_gets_futuristic_control_room_skin() -> None:
    assert '<link rel="stylesheet" href="/ui/person_studio_futuristic.css">' in HTML
    assert "radial-gradient" in FUTURE
    assert "backdrop-filter" in FUTURE
    assert "box-shadow" in FUTURE
    assert ".personality-workspace-frame-shell" in CSS
    assert "@keyframes personality-scan" in CSS


def test_personality_revision_deep_links_stay_inside_workspace() -> None:
    assert "personality-matrix-link" in JS
    assert "edit_revision" in JS
    assert "baseline_revision" in JS
    assert "openGuidedRevision" in JS
    assert 'params.set("embedded", "1")' in JS
    assert "styleEmbeddedFrame" in JS
    assert ".guided-head,.suite-head" in JS
