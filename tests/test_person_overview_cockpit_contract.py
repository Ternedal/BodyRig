from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.css").read_text(encoding="utf-8")


def test_person_overview_has_pipeline_cockpit() -> None:
    assert 'id="overviewCockpitStages"' in HTML
    assert 'id="overviewCockpitSummary"' in HTML
    assert 'id="overviewCockpitNext"' in HTML
    assert '<script src="/ui/person_overview_cockpit.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_overview_cockpit.css">' in HTML
    assert ".person-cockpit-stages" in CSS


def test_overview_cockpit_covers_full_person_pipeline() -> None:
    for label in ["1 · Source", "2 · Krop", "3 · Stemme", "4 · Personality", "5 · Person Revision", "6 · Digital twin"]:
        assert label in JS
    assert "active_person_revision" in JS
    assert "body_revisions" in JS
    assert "voice_revisions" in JS
    assert "personality_revisions" in JS
    assert "digital-twin-readiness" in JS


def test_overview_cockpit_is_read_only_and_navigates_to_existing_authority() -> None:
    assert 'method: "POST"' not in JS
    assert "/action" not in JS
    assert '.tab[data-tab="' in JS
    assert 'data-tab="operations"' not in JS  # HTML ownership stays in Person Studio; JS navigates generically.
    assert 'cache: "no-store"' in JS
