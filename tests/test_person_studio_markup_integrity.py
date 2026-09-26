from pathlib import Path


HTML = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")


def test_personality_workspace_closes_once_before_assemble_tab() -> None:
    bad = """          </article>
          </article>
        </section>

        <section id="tab-assemble""""
    assert bad not in HTML
    assert 'id="personalityWorkspaceFrame"' in HTML
    assert 'id="tab-assemble"' in HTML
