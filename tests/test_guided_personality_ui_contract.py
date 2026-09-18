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



def test_guided_studio_loads_server_defined_120_trait_matrix_v2() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")
    blueprint = Path("bodyrig/personality_blueprint.py").read_text(encoding="utf-8")

    for token in (
        "Personality Matrix v2 · 120 traits",
        "/api/v1/personality/trait-matrix",
        'id="innerTraits"',
        'id="outerTraits"',
        'id="traitSearch"',
        'id="resetTraits"',
        'inner_ring: traitPayload("inner")',
        'outer_ring: traitPayload("outer")',
        'inner.length!==60',
        'outer.length!==60',
        "Coordination findes bevidst i både Inner Ring og Outer Ring",
    ):
        assert token in html

    assert 'inner_ring: dict[str, Ratio] | None = None' in guided
    assert 'outer_ring: dict[str, Ratio] | None = None' in guided
    assert 'def personality_trait_matrix_definition() -> dict:' in guided
    assert '"bulk_apperception", "Bulk Apperception"' in blueprint
    assert '"knowledgeableness", "Knowledgeableness"' in blueprint
    assert '"egocentricism", "Egocentricism"' in blueprint
    assert '"aggression", "Aggression"' in blueprint
    assert blueprint.count('("coordination", "Coordination")') == 2



def test_guided_matrix_keeps_existing_personality_as_read_only_reference() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        'id="baselineRevision"',
        'id="baselineBadge"',
        'id="baselineInstructions"',
        'id="baselineStyleNotes"',
        "Baseline-reference påvirker ikke Matrix v2",
        "Source-derived speaking style bliver derfor ikke omskrevet til psykologiske traits",
        'get("baseline_revision")',
        'evidenceKind.startsWith("stash-source-")',
        'evidenceKind==="personality-blueprint-v2"',
        '$("baselineRevision").addEventListener("change",renderBaseline)',
    ):
        assert token in html

    payload_start = html.index("function payload(){")
    payload_end = html.index("function key(){", payload_start)
    payload_source = html[payload_start:payload_end]
    assert "baselineRevision" not in payload_source
    assert 'inner_ring: traitPayload("inner")' in payload_source
    assert 'outer_ring: traitPayload("outer")' in payload_source
