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


def test_guided_ui_requires_bound_report_and_approval_for_transcript_examples() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")
    authoring = Path("bodyrig/personality_authoring.py").read_text(encoding="utf-8")

    assert "/activate/" not in html
    assert 'id="styleReportFile" type="file"' in html
    assert 'id="styleApprovalFile" type="file"' in html
    assert "style_report: state.styleReport" in html
    assert "style_approval: state.styleApproval" in html
    assert "file.text()" in html
    assert "filstier sendes ikke til BodyRig" in html
    assert "candidate report og approval receipt" in html
    assert "style_report: dict[str, Any] | None" in guided
    assert "style_approval: dict[str, Any] | None" in guided
    assert "verify_approval(normalized_report, normalized_approval)" in authoring
    assert "style_report_sha256=" in authoring
    assert "style_approval_sha256=" in authoring
    assert "personality-style-evidence" in authoring
