from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP = (ROOT / "bodyrig" / "ui" / "overview_control_strip.js").read_text(encoding="utf-8")
COCKPIT = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.js").read_text(encoding="utf-8")


def test_overview_pipeline_readiness_is_structured() -> None:
    assert 'state.pipeline === "complete"' in STRIP
    assert "function text(id)" not in STRIP
    assert "/^Komplet$/i" not in STRIP


def test_overview_revision_binding_is_structured() -> None:
    assert 'state.revision === "bound"' in STRIP
    assert "/ingen/i" not in STRIP


def test_overview_state_is_published_from_cockpit_authority() -> None:
    assert "function publishOverviewControlState(" in COCKPIT
    assert 'root.dataset.pipelineState = pipelineState;' in COCKPIT
    assert 'root.dataset.revisionState = revisionState;' in COCKPIT
    assert 'root.dataset.twinState = twinState;' in COCKPIT
    assert 'root.dataset.nextLabel = nextLabel.slice(0, 1000);' in COCKPIT
    assert "publishOverviewControlUnknown();" in COCKPIT
