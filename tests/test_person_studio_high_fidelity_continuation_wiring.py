from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "high_fidelity_continuation.js").read_text(encoding="utf-8")

def test_person_studio_loads_existing_high_fidelity_continuation_ui() -> None:
    assert '<script src="/ui/high_fidelity_continuation.js" defer></script>' in HTML
    assert HTML.index('/ui/body_release_status.js') < HTML.index('/ui/high_fidelity_continuation.js')
    assert 'card.id = "highFidelityContinuationCard"' in JS
    assert '$("highFidelityPreviewCard") || $("bodyReviewGalleryCard")' in JS

def test_continuation_ui_keeps_canonical_action_boundary() -> None:
    assert '/continuation-status' in JS
    assert '/continuation-action' in JS
    assert 'method: "POST"' in JS
    assert 'operator_input_required' in JS
    assert 'production_ready === true && status.production_activation === true' in JS
