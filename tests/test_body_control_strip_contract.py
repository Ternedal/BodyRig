from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "body_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "body_control_strip.css").read_text(encoding="utf-8")


def test_body_tab_has_control_strip() -> None:
    for token in (
        'id="bodyControlStrip"',
        'id="bodyControlPreview"',
        'id="bodyControlReview"',
        'id="bodyControlRelease"',
        'id="bodyControlNext"',
    ):
        assert token in HTML
    assert '<script src="/ui/body_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/body_control_strip.css">' in HTML


def test_body_control_strip_reuses_existing_body_review_and_release_state() -> None:
    for token in (
        "bodyRevisionLabel",
        "bodyReviewGalleryBadge",
        "bodyReleaseBadge",
        "bodyReleaseNext",
        "bodyFidelityBadge",
        "bodyFidelityReviewBadge",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_body_control_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert "bodyReviewGalleryCard" in JS
    assert "bodyReleaseStatusCard" in JS
    assert "position:sticky" in CSS
