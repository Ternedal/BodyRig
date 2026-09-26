from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")

def test_body_candidates_can_be_inspected_without_activation() -> None:
    assert 'class="secondary inspect-body"' in JS
    assert 'function inspectBodyRevision(revisionId)' in JS
    assert 'renderBodyPreview(state.selected, body);' in JS
    assert 'target.querySelectorAll(".inspect-body")' in JS

def test_body_candidate_inspection_reuses_revision_bound_preview_and_vrm() -> None:
    section = JS.split("function renderBodyPreview", 1)[1].split("function inspectBodyRevision", 1)[0]
    assert '/body/preview?revision=${encodeURIComponent(body.revision_id)}' in section
    assert '/body/avatar?revision=${encodeURIComponent(body.revision_id)}' in section
    assert 'bodyControl.dataset.previewLabel = body?.revision_id || "Ingen revision";' in section

def test_body_candidate_inspection_does_not_mutate_person_or_assembly_authority() -> None:
    section = JS.split("function inspectBodyRevision", 1)[1].split("function resetVoiceTest", 1)[0]
    assert 'method: "POST"' not in section
    assert "activatePersonRevision" not in section
    assert "resetAssembly" not in section
    assert "renderSelected()" not in section
