from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_auto.js").read_text(encoding="utf-8")
SOURCE = (ROOT / "bodyrig" / "personality_source.py").read_text(encoding="utf-8")


def test_person_studio_loads_one_click_source_workflow() -> None:
    assert '<script src="/ui/person_auto.js" defer></script>' in HTML
    assert "Byg hele personen fra Stash" in JS
    assert "/body/build" in JS
    assert "/voice/build-from-source" in JS
    assert "/personality/build-from-source" in JS
    assert "/personality/guided/revisions" not in JS


def test_manual_voice_and_personality_are_not_primary_flow() -> None:
    assert "legacyPersonality.hidden = true" in JS
    assert "legacyVoice.hidden = true" in JS
    assert "Byg kun ny body-kandidat (avanceret)" in JS
    assert "Automatisk personality" in JS


def test_automatic_personality_uses_transcript_evidence_or_neutral_fallback() -> None:
    assert "transcript/caption-kilder" in JS
    assert "neutral source-bound fallback" in JS
    assert "body_revision=" in JS
    assert "Automatic source-derived personality from" in SOURCE
    assert "observed-speaking-style-only-not-biography-memory-beliefs-or-inner-personality" in SOURCE


def test_automatic_flow_survives_refresh_without_restarting_physical_body() -> None:
    assert "bodyrig-person-auto-v1" in JS
    assert "localStorage" in JS
    assert "body_job_id" in JS
    assert "Et fysisk body-build genstartes aldrig skjult efter et crash" in JS


def test_automatic_flow_stops_only_for_voice_disambiguation() -> None:
    assert 'job.status === "needs_speaker"' in JS
    assert 'job.status === "needs_reference"' in JS
    assert "person-buildet fortsætter automatisk bagefter" in JS


def test_automatic_body_progress_uses_backend_evidence_when_available() -> None:
    assert "renderBodyProgress" in JS
    assert "job.progress" in JS
    assert "job.message || job.stage" in JS
    assert "progress_kind" in JS
    assert "diagnostic_tail" in JS


def test_automatic_body_progress_never_claims_timer_as_real_percentage() -> None:
    assert "typisk 45–120 min" in JS
    assert "backend-progress" in JS
    assert "opdigtet procent" in JS
