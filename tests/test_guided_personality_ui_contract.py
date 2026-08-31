from pathlib import Path


def test_product_entrypoint_loads_guided_api_extension() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")
    start = Path("start-windows.ps1").read_text(encoding="utf-8")

    assert 'bodyrig = "bodyrig.guided_app:run"' in pyproject
    assert 'from .app import DEFAULT_HOST, DEFAULT_PORT, app, person_library' in guided
    assert 'uvicorn.run("bodyrig.guided_app:app"' in guided
    assert ".venv\\Scripts\\bodyrig.exe" in start


def test_guided_studio_exposes_structured_traits_preview_and_candidate_save() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        "Guided Personality",
        "directness",
        "warmth",
        "playfulness",
        "formality",
        "verbosity",
        "initiative",
        "bodyRevision",
        "style_exemplars",
        "/personality/guided/preview",
        "/personality/guided/revisions",
        "Gem som personality-kandidat",
        "Aktiv person er uændret",
    ):
        assert token in html

    assert "body_revision: $(\"bodyRevision\").value||null" in html
    assert "state.requestKey!==key()" in html
    assert "previewButton" in html
    assert "saveButton" in html


def test_guided_ui_does_not_offer_component_activation_or_transcript_bypass() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    assert "/activate/" not in html
    assert "--style-report" not in html
    assert "--style-approval" not in html
    assert "Transcript-eksempler skal gå gennem den separate approval-gate." in html
