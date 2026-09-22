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



def test_manual_person_change_isolates_person_scoped_guided_state() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    for token in (
        "personSelectionGeneration: 0",
        "personContextGeneration: 0",
        "transcriptLoadGeneration: 0",
        "deferredEditRevisionReload: null",
        "function isAcceptedPersonContext(personId,personContextGeneration=null)",
        "function isCurrentPerson(personId,personContextGeneration=null)",
        "personContextGeneration===state.personContextGeneration",
        "function setSelectedPersonUrl(personId,{clearRevision=false}={})",
        'url.searchParams.set("person_id",personId)',
        'url.searchParams.delete("edit_revision")',
        'url.searchParams.delete("baseline_revision")',
        "async function selectPerson(personId,{manual=false}={})",
        "const selectionGeneration=++state.personSelectionGeneration",
        "const previousPersonId=state.person?.person_id||null",
        'profile=await api(`/api/v1/people/${encodeURIComponent(personId)}`)',
        'if(selectionGeneration!==state.personSelectionGeneration||$("personSelect").value!==personId) return',
        "const changedPerson=previousPersonId!==personId",
        "state.person=profile",
        "if(manual) setSelectedPersonUrl(personId,{clearRevision:true})",
        "function resetPersonScopedAuthoring()",
        '$("language").value="da"',
        '$("feedback").value=""',
        '$("authoredNotes").value=""',
        '$("examples").replaceChildren()',
        "addExample()",
        "clearEvidence()",
        "if(changedPerson) resetPersonScopedAuthoring()",
        "state.person=null;\n      resetPersonScopedAuthoring()",
        'const personId=$("personSelect").value',
        "selectPerson(personId,{manual:true})",
        '$("personSelect").value=state.person?.person_id||""',
    ):
        assert token in html

    select_start = html.index("async function selectPerson(personId,{manual=false}={})")
    select_end = html.index("\n  function renderPreview", select_start)
    select_source = html[select_start:select_end]
    generation = select_source.index("const selectionGeneration=++state.personSelectionGeneration")
    fetch = select_source.index("profile=await api")
    accepted_guard = select_source.rindex(
        'if(selectionGeneration!==state.personSelectionGeneration||$("personSelect").value!==personId) return'
    )
    context_accept = select_source.index("state.personContextGeneration+=1", accepted_guard)
    assign = select_source.index("state.person=profile", context_accept)
    assert generation < fetch < accepted_guard < context_accept < assign
    assert select_source.count(
        'selectionGeneration!==state.personSelectionGeneration||$("personSelect").value!==personId'
    ) >= 2

    reset_start = html.index("function resetPersonScopedAuthoring()")
    reset_end = html.index("\n  function applyGuidedRevision", reset_start)
    reset_source = html[reset_start:reset_end]
    clear_evidence = reset_source.index("clearEvidence()")
    add_example = reset_source.index("addExample()")
    assert clear_evidence < add_example

    listener_start = html.index('$("personSelect").addEventListener("change"')
    listener_end = html.index('$("baselineRevision").addEventListener', listener_start)
    listener_source = html[listener_start:listener_end]
    assert listener_source.index('const personId=$("personSelect").value') < listener_source.index(
        "selectPerson(personId,{manual:true})"
    )
    assert 'if($("personSelect").value!==personId) return' in listener_source
    restore = listener_source.index('$("personSelect").value=state.person?.person_id||""')
    failed_save = listener_source.index('if($("status").textContent.startsWith("Gemning fejlede:"))', restore)
    reenable = listener_source.index('$("saveButton").disabled=!(state.preview&&state.requestKey===key())', failed_save)
    approval_restore = listener_source.index("updateTranscriptApprovalState()", reenable)
    deferred = listener_source.index("const deferred=state.deferredEditRevisionReload", approval_restore)
    deferred_guard = listener_source.index("if(deferred&&isCurrentPerson(deferred.personId,deferred.personContextGeneration))", deferred)
    deferred_clear = listener_source.index("state.deferredEditRevisionReload=null", deferred_guard)
    reload = listener_source.index("loadRequestedEditRevision().catch", deferred_clear)
    assert restore < failed_save < reenable < approval_restore < deferred < deferred_guard < deferred_clear < reload


def test_guided_person_async_results_cannot_cross_person_context() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")

    load_start = html.index("async function loadRequestedEditRevision()")
    load_end = html.index("\n  async function loadPeople()", load_start)
    load_source = html[load_start:load_end]
    assert 'const personId=state.person.person_id' in load_source
    assert "const personContextGeneration=state.personContextGeneration" in load_source
    source = load_source.index("const source=await api")
    accepted = load_source.index("if(!isAcceptedPersonContext(personId,personContextGeneration)) return", source)
    picker = load_source.index('if($("personSelect").value!==personId)', accepted)
    defer = load_source.index("state.deferredEditRevisionReload={personId,personContextGeneration}", picker)
    clear = load_source.index("state.deferredEditRevisionReload=null", defer)
    apply = load_source.index("applyGuidedRevision(source)", clear)
    assert source < accepted < picker < defer < clear < apply

    evidence_start = html.index("async function readEvidence(kind, file)")
    evidence_end = html.index("\n  function clearEvidence()", evidence_start)
    evidence_source = html[evidence_start:evidence_end]
    assert 'const personId=state.person?.person_id||null' in evidence_source
    assert "const personContextGeneration=state.personContextGeneration" in evidence_source
    assert 'const input=kind==="styleReport"?$("styleReportFile"):$("styleApprovalFile")' in evidence_source
    assert "state.personContextGeneration===personContextGeneration" in evidence_source
    assert '$("personSelect").value===personId' in evidence_source
    assert evidence_source.index("const value=JSON.parse(await file.text())") < evidence_source.index(
        "if(!stillCurrent()) return"
    ) < evidence_source.index("state[kind]=value")

    transcript_start = html.index("async function loadStashTranscriptCandidates()")
    transcript_end = html.index("\n  async function approveStashTranscriptCandidates()", transcript_start)
    transcript_source = html[transcript_start:transcript_end]
    assert 'const personId=state.person.person_id' in transcript_source
    assert "const personContextGeneration=state.personContextGeneration" in transcript_source
    assert "const transcriptLoadGeneration=++state.transcriptLoadGeneration" in transcript_source
    assert 'const loadingStatus="Validerer source-binding og leder efter transcript-sidecars…"' in transcript_source
    assert 'const isCurrentTranscriptContext=()=>isCurrentPerson(personId,personContextGeneration)&&$("bodyRevision").value===bodyRevision' in transcript_source
    assert "const settleStaleTranscriptLoad=()=>{" in transcript_source
    assert "transcriptLoadGeneration!==state.transcriptLoadGeneration" in transcript_source
    assert '$("stashTranscriptStatus").textContent===loadingStatus' in transcript_source
    assert "settleStaleTranscriptLoad()" in transcript_source

    approval_start = transcript_end + 1
    approval_end = html.index("\n  function renderEvidenceStatus()", approval_start)
    approval_source = html[approval_start:approval_end]
    assert "const personContextGeneration=state.personContextGeneration" in approval_source
    assert "const candidateReport=state.stashTranscriptPreview.candidate_report" in approval_source
    assert "candidate_report:candidateReport" in approval_source
    assert 'if(!isCurrentPerson(personId,personContextGeneration)||$("bodyRevision").value!==bodyRevision||state.stashTranscriptPreview?.candidate_report!==candidateReport) return' in approval_source

    preview_start = html.index("async function preview()")
    preview_end = html.index("\n  async function save()", preview_start)
    preview_source = html[preview_start:preview_end]
    assert "const personContextGeneration=state.personContextGeneration" in preview_source
    assert "const previewGeneration=++state.previewRequestGeneration" in preview_source
    assert "const requestKey=JSON.stringify(request)" in preview_source
    assert 'const previewStatus="Bygger og verifierer deterministisk blueprint…"' in preview_source
    assert "const settleStalePreview=()=>{" in preview_source
    assert 'previewGeneration===state.previewRequestGeneration&&$("status").textContent===previewStatus' in preview_source
    stale_guard = "if(!isCurrentPerson(personId,personContextGeneration)||key()!==requestKey)"
    result = preview_source.index("const result=await api")
    first_guard = preview_source.index(stale_guard, result)
    first_settle = preview_source.index("settleStalePreview()", first_guard)
    success_generation = preview_source.index(
        "if(previewGeneration!==state.previewRequestGeneration) return",
        first_settle,
    )
    render = preview_source.index("renderPreview(result)", success_generation)
    second_guard = preview_source.index(stale_guard, render)
    second_settle = preview_source.index("settleStalePreview()", second_guard)
    assert result < first_guard < first_settle < success_generation < render < second_guard < second_settle

    save_start = preview_end + 1
    save_end = html.index("\n\n  buildSliders();", save_start)
    save_source = html[save_start:save_end]
    assert "const personContextGeneration=state.personContextGeneration" in save_source
    assert "const saveGeneration=++state.saveRequestGeneration" in save_source
    assert "const saveViewKey=JSON.stringify(request)" in save_source
    assert "const currentSaveViewKey=()=>JSON.stringify" in save_source
    assert "const isCurrentSaveContext=()=>isCurrentPerson(personId,personContextGeneration)" in save_source
    assert "const previewStillValid=()=>Boolean(state.preview&&state.requestKey===key())" in save_source
    assert 'const savingStatus="Gemmer immutable blueprint/style-evidence og personality-kandidat…"' in save_source
    assert "const settleStaleSave=result=>" in save_source
    assert "if(saveGeneration!==state.saveRequestGeneration) return" in save_source
    assert 'if($("status").textContent===savingStatus)' in save_source
    assert 'toast(result.saved_personality_revision+" blev gemt, men editoren har ændret sig og blev ikke overskrevet.")' in save_source
    stale_start = save_source.index("const settleStaleSave=result=>")
    stale_end = save_source.index("};", stale_start)
    stale_source = save_source[stale_start:stale_end]
    assert 'if(isCurrentSaveContext()) $("saveButton").disabled=!previewStillValid()' in stale_source
    assert "const settleFailedSave=error=>" in save_source
    failed_start = save_source.index("const settleFailedSave=error=>")
    failed_end = save_source.index("const settleRefreshFailure=(result,error)=>", failed_start)
    failed_source = save_source[failed_start:failed_end]
    assert "if(saveGeneration!==state.saveRequestGeneration) return" in failed_source
    assert "if(!isAcceptedPersonContext(personId,personContextGeneration))" in failed_source
    assert 'if($("status").textContent===savingStatus) $("status").textContent=""' in failed_source
    assert 'if($("personSelect").value!==personId)' in failed_source
    assert "state.deferredSaveFailure={personId,personContextGeneration,saveGeneration,message:error.message,savingStatus}" in failed_source
    assert 'if(isCurrentSaveContext()) $("saveButton").disabled=!previewStillValid()' in failed_source
    assert "const settleRefreshFailure=(result,error)=>" in save_source
    refresh_failure_start = save_source.index("const settleRefreshFailure=(result,error)=>")
    refresh_failure_end = save_source.index("};", refresh_failure_start)
    refresh_failure_source = save_source[refresh_failure_start:refresh_failure_end]
    assert "profil-refresh fejlede" in refresh_failure_source
    assert "setEditRevisionUrl(result.saved_personality_revision)" in refresh_failure_source
    assert 'state.preview=null;state.requestKey=null;$("saveButton").disabled=true' in refresh_failure_source
    assert "settleFailedSave(error);" in save_source
    assert "settleRefreshFailure(result,error);" in save_source
    guard_text = "if(!isCurrentSaveContext()||currentSaveViewKey()!==saveViewKey)"
    first_guard = save_source.index(guard_text)
    first_settle = save_source.index("settleStaleSave(result)", first_guard)
    refresh = save_source.index("refreshedPerson=await api", first_settle)
    second_guard = save_source.index(guard_text, refresh)
    second_settle = save_source.index("settleStaleSave(result)", second_guard)
    context_refresh = save_source.index("state.personContextGeneration+=1", second_settle)
    assign = save_source.index("state.person=refreshedPerson", context_refresh)
    assert first_guard < first_settle < refresh < second_guard < second_settle < context_refresh < assign


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
    assert 'refreshedPerson=await api(`/api/v1/people/${encodeURIComponent(personId)}`)' in save_source
    assert "state.person=refreshedPerson" in save_source
    assert 'populateBaselines(); $("baselineRevision").value=result.saved_personality_revision; renderBaseline();' in save_source
    assert "Aktiv person er uændret" in save_source

    refresh = save_source.index(
        'refreshedPerson=await api(`/api/v1/people/${encodeURIComponent(personId)}`)'
    )
    guard = save_source.index(
        "if(!isCurrentSaveContext()||currentSaveViewKey()!==saveViewKey)",
        refresh,
    )
    assign = save_source.index("state.person=refreshedPerson", guard)
    assert refresh < guard < assign


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
    refresh = save_source.index(
        'refreshedPerson=await api(`/api/v1/people/${encodeURIComponent(personId)}`)'
    )
    guard = save_source.index(
        "if(!isCurrentSaveContext()||currentSaveViewKey()!==saveViewKey)",
        refresh,
    )
    assign = save_source.index("state.person=refreshedPerson", guard)
    update_url = save_source.index("setEditRevisionUrl(result.saved_personality_revision)", assign)
    assert refresh < guard < assign < update_url

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


def test_failed_person_switch_resyncs_comparisons_and_reconciles_successful_save() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(encoding="utf-8")
    signature = Path("bodyrig/ui/personality_signature.js").read_text(encoding="utf-8")
    matrix = Path("bodyrig/ui/personality_matrix.js").read_text(encoding="utf-8")

    assert "deferredSaveReconciliation: null" in html
    assert "deferredSaveFailure: null" in html
    assert "function discardDeferredSaveFailure()" in html
    assert "function settleDeferredSaveFailure()" in html
    assert "const deferSavedResult=(result,refreshedPerson=null)=>" in html
    assert "state.deferredSaveReconciliation={personId,personContextGeneration,saveGeneration,result,saveViewKey,refreshedPerson}" in html
    assert "if(deferSavedResult(result)) return" in html
    assert "if(deferSavedResult(result,refreshedPerson)) return" in html
    assert "async function reconcileDeferredSave()" in html
    assert "const deferred=state.deferredSaveReconciliation" in html
    assert "state.deferredSaveReconciliation=null" in html
    assert "const editorUnchanged=JSON.stringify({...payload(),feedback:$(\"feedback\").value.trim()})===deferred.saveViewKey" in html
    assert "setEditRevisionUrl(deferred.result.saved_personality_revision)" in html
    assert "state.person=refreshedPerson" in html

    listener_start = html.index('$(\"personSelect\").addEventListener(\"change\"')
    listener_end = html.index('$(\"baselineRevision\").addEventListener', listener_start)
    listener_source = html[listener_start:listener_end]
    restore = listener_source.index('$(\"personSelect\").value=state.person?.person_id||\"\"')
    resync = listener_source.index('document.dispatchEvent(new CustomEvent(\"bodyrig:person-context-restored\"', restore)
    failed_save = listener_source.index("settleDeferredSaveFailure()", resync)
    deferred_save = listener_source.index("const deferredSave=state.deferredSaveReconciliation", failed_save)
    reconcile = listener_source.index("reconcileDeferredSave().catch", deferred_save)
    deferred_revision = listener_source.index("const deferred=state.deferredEditRevisionReload", reconcile)
    assert restore < resync < failed_save < deferred_save < reconcile < deferred_revision

    assert 'document.addEventListener("bodyrig:person-context-restored", scheduleRender)' in signature
    matrix_restore = 'document.addEventListener("bodyrig:person-context-restored", () => {'
    assert matrix_restore in matrix
    matrix_start = matrix.index(matrix_restore)
    matrix_end = matrix.index("});", matrix_start)
    matrix_source = matrix[matrix_start:matrix_end]
    assert matrix_source.index("syncCompareOptions();") < matrix_source.index("scheduleRender();")
