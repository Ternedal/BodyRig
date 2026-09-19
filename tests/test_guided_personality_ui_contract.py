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



def test_guided_matrix_surfaces_changed_trait_workflow() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        'id="changedTraitsOnly"',
        'id="traitChangeSummary"',
        "Kun ændrede",
        "0 / 120 traits ændret fra neutral 0.50.",
        "function updateTraitView()",
        'Math.abs(Number(input.value)-0.5)>0.000001',
        '$("changedTraitsOnly").addEventListener("change",updateTraitView)',
        'placeholder="Fx Matrix v2 refinement"',
    ):
        assert token in html


def test_guided_matrix_reloads_provenance_after_save() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    save_start = html.index("async function save(){")
    save_end = html.index("buildSliders();", save_start)
    save_source = html[save_start:save_end]
    assert 'state.person=await api(`/api/v1/people/${encodeURIComponent(personId)}`)' in save_source
    assert 'populateBaselines(); $("baselineRevision").value=result.saved_personality_revision; renderBaseline();' in save_source
    assert "Aktiv person er uændret" in save_source


def test_guided_matrix_save_persists_edit_revision_in_url() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        "function isMatrixRevisionItem(item)",
        "function latestMatrixRevisionItem()",
        "function setEditRevisionUrl(revisionId)",
        'url.searchParams.set("edit_revision",revisionId)',
        "history.replaceState",
        "const fallback=latestMatrixRevisionItem()?.revision_id||",
        "const revisionId=requested||fallback",
        "if(!requested) setEditRevisionUrl(revisionId)",
        "setEditRevisionUrl(result.saved_personality_revision)",
    ):
        assert token in html

    save_start = html.index("async function save(){")
    save_end = html.index("buildSliders();", save_start)
    save_source = html[save_start:save_end]
    assert save_source.index("setEditRevisionUrl(result.saved_personality_revision)") < save_source.index(
        'state.person=await api(`/api/v1/people/${encodeURIComponent(personId)}`)'
    )

def test_guided_matrix_can_reopen_verified_v2_revision() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")

    for token in (
        'get("edit_revision")',
        "function applyGuidedRevision(source)",
        "function loadRequestedEditRevision()",
        '/personality/guided/revisions/${encodeURIComponent(revisionId)}',
        "Kun Personality Matrix v2-revisioner kan genåbnes som redigerbar matrix.",
        'state.styleEvidenceOrigin=(state.styleReport&&state.styleApproval)?"revision":null',
        "Transcript-evidence genindlæst og verifieret fra den immutable personality-revision",
        "load_guided_personality_revision",
    ):
        assert token in html or token in guided

    assert '@app.get("/api/v1/people/{person_id}/personality/guided/revisions/{revision_id}")' in guided



def test_reopened_matrix_remains_saved_until_operator_changes_it() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    apply_start = html.index("function applyGuidedRevision(source)")
    apply_end = html.index("async function loadRequestedEditRevision()", apply_start)
    apply_source = html[apply_start:apply_end]

    assert "updateTraitView();" in apply_source
    assert "state.preview=null; state.requestKey=null" in apply_source
    assert '$("saveButton").disabled=true' in apply_source
    assert '$("blueprintBadge").textContent=source.blueprint_sha256.slice(0,12)+"…"' in apply_source
    assert "gemt revision." in apply_source
    assert "invalidate();" not in apply_source

    # Real trait authoring changes still use the normal invalidation path.
    assert '$(inputId).addEventListener("input",()=>{' in html
    assert "updateTraitView(); invalidate();" in html


def test_guided_matrix_can_explicitly_stack_verified_source_baseline() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")

    for token in (
        'id="stackBaseline"',
        "Bevar verificeret source speaking-style",
        "Kun en source-derived Stash personality kan stackes.",
        'baseline_revision: $("stackBaseline").checked',
        'stackToggle.disabled=!sourceBaseline',
        'source_baseline_revision',
        "Personality stack:",
        '$("stackBaseline").addEventListener("change",invalidate)',
        'baseline_revision: str | None = Field(default=None, max_length=24)',
        '"baseline_revision": request.baseline_revision',
    ):
        assert token in html or token in guided

    payload_start = html.index("function payload(){")
    payload_end = html.index("function key(){", payload_start)
    payload_source = html[payload_start:payload_end]
    assert "baseline_revision" in payload_source
    assert "stackBaseline" in payload_source


def test_reopened_stack_restores_exact_source_baseline_selection() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    apply_start = html.index("function applyGuidedRevision(source)")
    apply_end = html.index("async function loadRequestedEditRevision()", apply_start)
    apply_source = html[apply_start:apply_end]
    assert "source.source_baseline_revision||null" in apply_source
    assert '$("stackBaseline").checked=Boolean(stackedBaseline)' in apply_source


def test_guided_matrix_surfaces_authored_signature_traits() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    signature = Path("bodyrig/ui/personality_signature.js").read_text(encoding="utf-8")

    assert '<script src="/ui/personality_signature.js"></script>' in html
    for token in (
        'signatureTarget.id = "traitSignature"',
        "Signature traits · størst authored afvigelse fra neutral",
        "signature.slice(0, LIMIT)",
        "Math.abs(entry.value - NEUTRAL)",
        'left.label.localeCompare(right.label, "da")',
        'entry.value > NEUTRAL ? "↑" : "↓"',
        'entry.input.closest(".trait-ring")',
        'search.dispatchEvent(new Event("input", { bubbles: true }))',
        'changedOnly.dispatchEvent(new Event("change", { bubbles: true }))',
        "Ingen traits afviger fra neutral endnu.",
    ):
        assert token in signature

    assert "personality_authority" not in signature
    assert "production_activation" not in signature


def test_guided_matrix_compares_current_traits_with_verified_revision_baseline() -> None:
    signature = Path("bodyrig/ui/personality_signature.js").read_text(encoding="utf-8")

    for token in (
        "Revision delta · mod valgt Matrix v2 baseline",
        'deltaTarget.id = "traitRevisionDelta"',
        "async function loadBaselineIfNeeded()",
        "/personality/guided/revisions/",
        "encodeURIComponent(selection.personId)",
        "encodeURIComponent(selection.revision)",
        "validMatrixBlueprint(source?.blueprint)",
        "Object.keys(value.inner_ring).length === 60",
        "Object.keys(value.outer_ring).length === 60",
        'baselineState.status = "unavailable"',
        'baselineState.status = "ready"',
        "const signedDelta = entry.value - baselineValue",
        "Math.abs(signedDelta)",
        "Δ ${sign}${entry.signedDelta.toFixed(2)}",
        "Delta gemmes ikke.",
        'new MutationObserver(scheduleRender).observe(baselineSelect',
        'const compareSelect = document.getElementById("matrixCompareRevision")',
        '? compareSelect.value',
        'document.addEventListener("bodyrig:matrix-compare-change", scheduleRender)',
    ):
        assert token in signature

    render_start = signature.index("function render()")
    render_end = signature.index("let scheduled", render_start)
    render_source = signature[render_start:render_end]
    assert render_source.index("void loadBaselineIfNeeded()") < render_source.index(
        "renderRevisionDelta(targets.deltaTarget, entries)"
    )

    assert "style_report" not in signature
    assert "personality_authority" not in signature
    assert "production_activation" not in signature


def test_guided_matrix_trait_rows_do_not_force_two_columns() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    assert ".trait-grid{display:grid;grid-template-columns:1fr;gap:2px" in html
    assert "grid-template-columns:minmax(150px,.9fr) minmax(180px,1.6fr) 52px" in html
    assert ".trait-slider-row input{width:100%;min-width:0}" in html
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" not in html


def test_guided_matrix_radial_editor_is_ui_only() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    matrix = Path("bodyrig/ui/personality_matrix.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/personality_matrix.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/ui/personality_matrix.css">' in html
    assert '<script src="/ui/personality_matrix.js"></script>' in html

    for token in (
        'id = "personalityMatrixCockpit"',
        "PERSONALITY MATRIX V2 · RADIAL EDITOR",
        'data-ring="inner"',
        'data-ring="outer"',
        'id="personalityMatrixSvg"',
        'id="matrixCompareRevision"',
        'id="matrixPreviewButton"',
        'id="matrixSaveButton"',
        'id="matrixAuditionLink"',
        "Test denne revision · 6 scenarier",
        'stateName === "saved"',
        'get("edit_revision")',
        "revisionExists",
        "/ui/personality_audition_suite.html?person_id=",
        "&personality_revision=",
        "function syncSaveControls()",
        'const previewPrimary = stateName === "dirty"',
        'const savePrimary = stateName === "ready"',
        'mirrorPreview.classList.toggle("primary", previewPrimary)',
        'mirrorSave.classList.toggle("primary", savePrimary)',
        'mirrorSave.classList.toggle("secondary", !savePrimary)',
        '$("matrixPreviewButton")?.addEventListener("click", () => $("previewButton")?.click())',
        '$("matrixSaveButton")?.addEventListener("click", () => $("saveButton")?.click())',
        '"Ikke gemte ændringer"',
        '"Preview klar"',
        '"Gemt"',
        "genindlæst fra verificeret blueprint",
        "function syncCompareOptions()",
        'option.textContent.includes("Matrix v2")',
        "Ingen tidligere Matrix v2-revisioner",
        "option.value !== editingRevision",
        'new CustomEvent("bodyrig:matrix-compare-change")',
        "polygonPoints(entries",
        "matrix-current-shape",
        "matrix-baseline-shape",
        "matrixInspectorRange",
        "pointerdown",
        "pointermove",
        "setPointerCapture",
        "updateDraggedTrait(svg, event)",
        "Math.round(clamped / 0.05) * 0.05",
        '"data-trait-id": entry.traitId',
        'entry.input.dispatchEvent(new Event("input", { bubbles: true }))',
        "Vis rå 120 sliders",
        "Skjul rå 120 sliders",
        "Kun de mest markante labels vises; alle 60 akser er tegnet.",
        "/personality/guided/revisions/",
        "Object.keys(value.inner_ring).length === 60",
        "Object.keys(value.outer_ring).length === 60",
    ):
        assert token in matrix

    assert ".guided-shell{max-width:1440px}" in css
    assert ".guided-grid{grid-template-columns:minmax(0,1fr)}" in css
    assert "body.matrix-raw-hidden .trait-rings" in css
    assert ".matrix-stage" in css
    assert ".matrix-compare-control" in css
    assert ".matrix-save-panel" in css
    assert ".matrix-save-state[data-state=\"saved\"]" in css
    assert ".matrix-save-actions" in css
    assert ".matrix-audition-link" in css
    assert matrix.index('class="matrix-save-panel"') < matrix.index('</aside>')
    assert ".matrix-current-shape" in css
    assert ".matrix-baseline-shape" in css
    assert "touch-action:none" in css
    assert ".matrix-svg.dragging{cursor:grabbing}" in css
    assert "maxScore <= EPSILON" in matrix
    assert "Math.floor((slot * entries.length) / LABEL_LIMIT)" in matrix
    assert 'state.selectedId = entries[0].traitId' in matrix
    assert 'item.x = side === "right" ? SIZE - 62 : 62' in matrix
    assert "const gap = 27" in matrix
    assert 'event.target.closest?.("#traitSignature button, #traitRevisionDelta button")' in matrix

    render_start = matrix.index("function render()")
    render_end = matrix.index("function scheduleRender()", render_start)
    render_source = matrix[render_start:render_end]
    assert render_source.index("void loadBaselineIfNeeded()") < render_source.index(
        "renderSvg(entries, selected)"
    )

    # The radial editor reads/writes the already-authored slider controls only.
    # It must not mint evidence or claim authority of its own.
    for forbidden in ("personality_authority", "production_activation", "style_report"):
        assert forbidden not in matrix

    # Cockpit actions must proxy the existing preview/save controls rather than
    # bypassing the established request-key and preview gate with their own POST.
    assert 'method:"POST"' not in matrix
