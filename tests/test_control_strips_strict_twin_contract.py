from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = (ROOT / "bodyrig" / "ui" / "operations_control_strip.js").read_text(encoding="utf-8")
OVERVIEW = (ROOT / "bodyrig" / "ui" / "overview_control_strip.js").read_text(encoding="utf-8")

def test_operations_strip_requires_structured_strict_m6_state() -> None:
    assert 'setChip("operationsControlTwin", state.twin.label, state.twin.state === "ready");' in OPS
    assert 'twin: new Set(["ready", "blocked", "unknown", "checking"])' in OPS
    assert "badState" not in OPS
    assert '/klar|ready|pass|aktiv/i' not in OPS

def test_overview_strip_requires_strict_m6_ready_badge() -> None:
    assert 'setChip("overviewControlTwin",twin||"Ukendt",/^M6 klar$/i.test(twin));' in OVERVIEW
    assert '/klar|ready|pass|aktiv/i' not in OVERVIEW
