from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "history_control_strip.js").read_text(encoding="utf-8")
PERSON_JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "history_control_strip.css").read_text(encoding="utf-8")


def test_history_tab_has_control_strip() -> None:
    for token in (
        'id="historyControlStrip"',
        'id="historyControlActive"',
        'id="historyControlRevisions"',
        'id="historyControlComponents"',
        'id="historyControlNext"',
    ):
        assert token in HTML
    assert '<script src="/ui/history_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/history_control_strip.css">' in HTML


def test_history_strip_is_read_only_navigation() -> None:
    assert "historyList" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert '.tab[data-tab="overview"]' in JS
    assert '.tab[data-tab="assemble"]' in JS
    assert "position:sticky" in CSS


def test_history_strip_requires_profile_derived_strict_summary() -> None:
    for token in (
        "historyLoaded",
        "historyIntegrity",
        "historyRevisionCount",
        "historyActiveRevision",
        "historyActiveState",
        "historyActiveComponentCount",
    ):
        assert token in JS
        assert token in PERSON_JS

    assert "function strictHistoryState()" in JS
    assert 'state.activeState === "ready"' in JS
    assert "state.activeComponentCount === 3" in JS
    assert "state.integrityValid" in JS
    assert "countHistory" not in JS
    assert 'text("personActive")' not in JS
    assert 'text("bodyActive")' not in JS
    assert 'text("voiceActive")' not in JS
    assert 'text("personalityActive")' not in JS


def test_person_app_summary_fails_closed_on_missing_or_ambiguous_bindings() -> None:
    assert "function buildHistorySummary(profile)" in PERSON_JS
    assert "seen.has(key)" in PERSON_JS
    assert "personMatches.length !== 1" in PERSON_JS
    assert 'activeRevisionState: "missing"' in PERSON_JS
    assert 'activeRevisionState: activeComponentCount === 3 ? "ready" : "incomplete"' in PERSON_JS
    assert "matches.length === 1" in PERSON_JS
    assert 'target.dataset.historyIntegrity = summary.integrityValid ? "valid" : "invalid"' in PERSON_JS
    assert 'target.dataset.historyLoaded = "true"' in PERSON_JS
