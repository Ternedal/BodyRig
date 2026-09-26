from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "bodyrig" / "ui" / "body_control_strip.js").read_text(encoding="utf-8")

def test_body_review_requires_exact_hash_bound_state() -> None:
    assert '/^4\\/4 hash-bundet$/i.test(reviewBadge)' in JS
    assert '/4\\/4|pass|hash-bundet/i' not in JS

def test_body_release_requires_exact_production_ready_state() -> None:
    assert '/^Production klar$/i.test(releaseBadge)' in JS
    assert '/pass|klar|aktiv|released/i' not in JS

def test_body_fidelity_next_step_uses_canonical_badges() -> None:
    assert '/^Review PASS$/i.test(fidelityReview)' in JS
    assert '/^HF-komponenter komplette$/i.test(fidelityBadge)' in JS
