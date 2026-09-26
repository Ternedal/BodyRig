from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "assembly_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "assembly_control_strip.css").read_text(encoding="utf-8")


def test_assemble_tab_has_control_strip() -> None:
    for token in (
        'id="assemblyControlStrip"',
        'id="assemblyControlSelection"',
        'id="assemblyControlAudition"',
        'id="assemblyControlReview"',
        'id="assemblyControlNext"',
    ):
        assert token in HTML
    assert '<script src="/ui/assembly_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/assembly_control_strip.css">' in HTML


def test_assembly_control_strip_reuses_structured_audition_and_review_state() -> None:
    for token in (
        'root.dataset.stateVersion !== "1"',
        "selectionState",
        "selectionCount",
        "auditionState",
        "reviewState",
        '"data-selection-state"',
        '"data-audition-state"',
        '"data-review-state"',
    ):
        assert token in JS
    for forbidden in (
        "assemblyFingerprint",
        "assemblyBodyState",
        "assemblyVoiceState",
        "assemblyPersonalityState",
        "assemblyReadyBadge",
        "function text(id)",
    ):
        assert forbidden not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_assembly_control_strip_preserves_human_review_boundary() -> None:
    assert "approvePersonButton" not in JS
    assert "scrollIntoView" in JS
    assert "eksplicit menneskelig vurdering" in JS
    assert "position:sticky" in CSS

def test_person_app_publishes_structured_assembly_state() -> None:
    app = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
    assert "function publishAssemblyControlState()" in app
    assert 'root.dataset.selectionState = selectionComplete ? "ready" : "incomplete";' in app
    assert 'root.dataset.auditionState = auditionState;' in app
    assert 'root.dataset.reviewState = reviewState;' in app
    assert "publishAssemblyControlState();" in app
