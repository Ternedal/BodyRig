from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "person_topology.js").read_text(encoding="utf-8")

def test_topology_requires_strict_m6_ready_badge() -> None:
    assert 'const twinReady = /^M6 klar$/i.test(twinBadge);' in JS
    assert '/klar|pass|ready|aktiv/i' not in JS
    assert 'operator-digital-twin-badge' in JS
    assert 'operator-digital-twin-summary' in JS
