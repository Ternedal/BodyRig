from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "person_topology.js").read_text(encoding="utf-8")

def test_topology_requires_explicit_structured_twin_ready_state() -> None:
    assert 'const twinReady = state.twin.state === "ready";' in JS
    assert '/klar|pass|ready|aktiv/i' not in JS
    assert 'operator-digital-twin-badge' not in JS
    assert 'operator-digital-twin-summary' not in JS

def test_overview_publishes_structured_topology_state() -> None:
    overview = (ROOT / "bodyrig" / "ui" / "person_overview_cockpit.js").read_text(encoding="utf-8")
    assert "function publishTopologyState(profile, bundle, digitalTwin)" in overview
    assert "function publishTopologyUnknown()" in overview
    assert 'root.dataset.twinState = twinReady ? "ready" : "not-ready";' in overview
    assert 'root.dataset.coreState = revision && bundle ? "bound" : (revision ? "invalid" : "unbound");' in overview
    assert "publishTopologyState(profile, bundle, digitalTwin);" in overview
    assert "publishTopologyUnknown();" in overview
