from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "overview_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "overview_control_strip.css").read_text(encoding="utf-8")

def test_overview_tab_has_control_strip() -> None:
    for token in ('id="overviewControlStrip"','id="overviewControlPipeline"','id="overviewControlRevision"','id="overviewControlTwin"','id="overviewControlNext"'):
        assert token in HTML
    assert '<script src="/ui/overview_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/overview_control_strip.css">' in HTML

def test_overview_strip_reuses_structured_state() -> None:
    for token in (
        'root.dataset.stateVersion !== "1"',
        "pipelineState",
        "revisionState",
        "twinState",
        "nextLabel",
        '"data-pipeline-state"',
        '"data-revision-state"',
        '"data-twin-state"',
        '"data-next-label"',
    ):
        assert token in JS
    for forbidden in ("overviewCockpitBadge", "overviewPersonRevision", "operator-digital-twin-badge", "overviewCockpitAttention"):
        assert forbidden not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS

def test_overview_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert '.tab[data-tab="history"]' in JS
    assert '.tab[data-tab="operations"]' in JS
    assert "position:sticky" in CSS
