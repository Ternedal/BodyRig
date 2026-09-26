from pathlib import Path


def test_person_studio_embeds_selected_person_into_guided_and_suite_tools() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/personality_workspace.js").read_text(encoding="utf-8")

    for token in (
        'id="personalityWorkspaceGuided"',
        'id="personalityWorkspaceSuite"',
        'id="personalityWorkspaceFrame"',
        "Guided Personality",
        "6-scenarie audition",
    ):
        assert token in html

    for token in (
        "/ui/personality_guided.html",
        "/ui/personality_audition_suite.html",
        "person_id=",
        "encodeURIComponent(id)",
    ):
        assert token in js


def test_personality_workspace_does_not_add_activation_or_api_mutation() -> None:
    js = Path("bodyrig/ui/personality_workspace.js").read_text(encoding="utf-8")

    assert "fetch(" not in js
    assert 'method: "POST"' not in js
    assert "/action" not in js
    assert "activate" not in js.lower()
    assert "window.open" in js
