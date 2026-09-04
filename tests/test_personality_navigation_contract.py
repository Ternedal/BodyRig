from pathlib import Path


def test_person_studio_links_selected_person_to_guided_and_suite_tools() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")

    for token in (
        'id="guidedPersonalityLink"',
        'id="personalitySuiteLink"',
        "/ui/personality_guided.html?person_id=",
        "/ui/personality_audition_suite.html?person_id=",
        "encodeURIComponent(document.getElementById('personId').textContent)",
        "Guided Personality",
        "Kør 6-scenarie audition",
    ):
        assert token in html

    assert "Guided Personality opretter kun kandidater" in html
    assert "supplementary review-evidence" in html
    assert "ikke activation-authority" in html


def test_personality_navigation_does_not_add_activation_or_api_mutation() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    start = html.index('<article class="card space-top">\n            <div class="card-row">\n              <div><div class="card-label">Personality-værktøjer</div>')
    end = html.index("</article>", start) + len("</article>")
    tools = html[start:end]

    assert "fetch(" not in tools
    assert "/api/" not in tools
    assert "/activate/" not in tools
    assert "person_id" in tools
