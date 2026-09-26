from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP = (ROOT / "bodyrig" / "ui" / "body_control_strip.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
REVIEW = (ROOT / "bodyrig" / "ui" / "body_review_gallery.js").read_text(encoding="utf-8")
RELEASE = (ROOT / "bodyrig" / "ui" / "body_release_status.js").read_text(encoding="utf-8")


def test_body_strip_has_no_rendered_label_readiness_parsing() -> None:
    assert "function text(id)" not in STRIP
    assert "4/4 hash-bundet" not in STRIP
    assert "Production klar" not in STRIP
    assert "Review PASS" not in STRIP
    assert "HF-komponenter komplette" not in STRIP


def test_body_preview_state_is_published_from_profile_render() -> None:
    assert 'bodyControl.dataset.previewState = body ? "ready" : "missing";' in APP
    assert 'bodyControl.dataset.previewLabel = body?.revision_id || "Ingen revision";' in APP
    assert 'bodyControl.dataset.previewState = "unknown";' in APP


def test_body_review_state_is_published_from_review_validator() -> None:
    assert "function publishReviewState(state, label)" in REVIEW
    assert 'publishReviewState("checking", "Validerer 4 views");' in REVIEW
    assert 'publishReviewState("ready", "4/4 hash-bundet");' in REVIEW
    assert 'publishReviewState("blocked", "Review ugyldig");' in REVIEW


def test_body_release_state_is_published_from_release_payload() -> None:
    assert "function publishBodyControlReleaseState(" in RELEASE
    assert 'releaseState: production ? "ready"' in RELEASE
    assert 'fidelityState: fidelityReady ? "ready" : "blocked"' in RELEASE
    assert 'fidelityReviewState: fidelityReviewReady' in RELEASE
    assert 'releaseState: "checking"' in RELEASE
    assert 'releaseState: "unknown"' in RELEASE
