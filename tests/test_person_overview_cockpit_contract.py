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



def test_cockpit_ready_component_candidates_advance_instead_of_looping_back() -> None:
    assert "function stageSatisfiesPipeline(stage)" in JS
    assert 'stage.key === "body" || stage.key === "voice" || stage.key === "personality"' in JS
    assert 'stage.state === "ready" || stage.state === "complete"' in JS
    assert "if (stage && !stageSatisfiesPipeline(stage)) return stage;" in JS
    assert "pipelineSatisfied" in JS
    assert "pipeline-trin klar" in JS


def test_cockpit_fails_closed_on_missing_active_person_revision_binding() -> None:
    assert "requestedPersonRevision" in JS
    assert "assemblyInconsistent" in JS
    assert 'state: assembled ? "complete" : (assemblyInconsistent ? "blocked" : "missing")' in JS
    assert '"Ugyldig binding"' in JS
    assert "revisionen findes ikke i person_revisions" in JS
    assert "const twinReady = assembled" in JS


def test_overview_cockpit_surfaces_person_scoped_operator_attention() -> None:
    assert 'id="overviewCockpitAttention"' in HTML
    assert ".person-cockpit-attention" in CSS
    assert "function authoritativePersonJobs(id)" in JS
    assert "/api/v1/jobs?person_id=" in JS
    assert "/api/v1/jobs/${encodeURIComponent(jobId)}" in JS
    assert "/body/photoreal-control-plane" in JS
    assert "function operatorAttention(profile, jobsRead, photorealRead, twinRead)" in JS
    assert "Aktuel operator-opmærksomhed" in JS


def test_overview_attention_prioritizes_explicit_input_and_current_blockers() -> None:
    assert 'new Set(["needs_speaker", "needs_reference"])' in JS
    assert "Stemme kræver speaker-valg" in JS
    assert "Stemme kræver reference-valg" in JS
    assert "VoiceRig-status kan ikke bekræftes" in JS
    assert "ExAvatar kan være stalled" in JS
    assert "Photoreal er blokeret" in JS
    assert "Photoreal kræver human review" in JS
    assert "Digital-twin status kan ikke bekræftes" in JS
    assert ".find((item) => Number(item?.priority || 0) >= 80)" in JS
    assert 'key: "operator-attention"' in JS


def test_overview_attention_keeps_historical_job_failure_below_immediate_override() -> None:
    assert "function latestJobPerKind(jobs)" in JS
    assert '["failed", "interrupted"].includes(status)' in JS
    assert "Seneste voice-build fejlede" in JS
    assert "Seneste body-build fejlede" in JS
    assert '70,\n        "blocked"' in JS
    assert ">= 80" in JS


def test_overview_attention_remains_read_only() -> None:
    assert 'method: "POST"' not in JS
    assert "/action" not in JS
    assert "shell" not in JS.lower()
    assert "next_command" not in JS
    assert "confirm_production_activation" not in JS
