from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "personality_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "personality_control_strip.css").read_text(encoding="utf-8")


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


def test_personality_control_strip_reuses_existing_state() -> None:
    for token in ("personalityRevisions", "personalityWorkspaceStatus", "personalityActive"):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_personality_control_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert '.tab[data-tab="assemble"]' in JS
    assert "position:sticky" in CSS


def test_personality_candidate_count_ignores_empty_placeholder() -> None:
    assert 'querySelectorAll(".revision-item").length' in JS
    assert '[...host.children]' not in JS


def test_personality_lab_readiness_requires_exact_workspace_status() -> None:
    workspace = (
        ROOT / "bodyrig" / "ui" / "personality_workspace.js"
    ).read_text(encoding="utf-8")

    guided = "Guided Personality · kandidat-authoring for valgt person."
    suite = "6-scenarie audition · supplementary review-evidence for valgt person."

    assert "function personalityLabReady(value)" in JS
    assert guided in JS
    assert suite in JS
    assert guided in workspace
    assert suite in workspace
    assert "personalityLabReady(lab)" in JS
    assert "!/fejl|ikke klar/i.test(lab)" not in JS
