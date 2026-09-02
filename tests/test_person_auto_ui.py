from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_auto.js").read_text(encoding="utf-8")


def test_person_studio_loads_automatic_source_workflow() -> None:
    assert '<script src="/ui/person_auto.js" defer></script>' in HTML
    assert "Automatisk stemme fra personens Stash-kilder" in JS
    assert "/voice/build-from-source" in JS
    assert "Byg stemmen automatisk" in JS


def test_personality_no_longer_starts_as_manual_blank_primary_flow() -> None:
    assert "Automatisk personality fra samme person-authority" in JS
    assert "/personality/guided/revisions" in JS
    assert "Byg personality automatisk" in JS
    assert "oldPersonality.hidden = true" in JS
    assert "oldVoice.hidden = true" in JS


def test_automatic_personality_is_source_conservative() -> None:
    assert "Do not invent biography, memories, relationships, private facts" in JS
    assert "body_revision: bodyRevision" in JS
