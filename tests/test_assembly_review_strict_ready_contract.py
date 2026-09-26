from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "assembly_control_strip.js").read_text(encoding="utf-8")

def test_assembly_review_readiness_requires_exact_badge() -> None:
    assert 'const reviewReady = /^Klar til review$/i.test(readyBadge);' in JS
    assert '/klar|ready|pass|godkend/i' not in JS
