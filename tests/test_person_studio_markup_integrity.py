from pathlib import Path


HTML = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")


def test_personality_workspace_closes_once_before_assemble_tab() -> None:
    duplicate_close = (
        '          </article>\n'
        '          </article>\n'
        '        </section>\n\n'
        '        <section id="tab-assemble"'
    )
    assert duplicate_close not in HTML
    assert 'id="personalityWorkspaceFrame"' in HTML
    assert 'id="tab-assemble"' in HTML
