from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
GALLERY = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "high_fidelity_continuation.js").read_text(encoding="utf-8")

def test_person_studio_loads_existing_high_fidelity_continuation_ui_once() -> None:
    assert '<script src="/ui/body_review_gallery.js" defer></script>' in HTML
    assert '<script src="/ui/high_fidelity_continuation.js" defer></script>' not in HTML
    assert 'void import("/ui/high_fidelity_continuation.js")' in GALLERY
    assert 'card.id = "highFidelityContinuationCard"' in JS
    assert '$("highFidelityPreviewCard") || $("bodyReviewGalleryCard")' in JS

def test_continuation_ui_keeps_canonical_action_boundary() -> None:
    assert '/continuation-status' in JS
    assert '/continuation-action' in JS
    assert 'method: "POST"' in JS
    assert 'operator_input_required' in JS
    assert 'production_ready === true && status.production_activation === true' in JS
