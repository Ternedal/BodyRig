from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP = (ROOT / "bodyrig" / "ui" / "assembly_control_strip.js").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")


def test_assembly_review_readiness_requires_structured_state() -> None:
    assert 'state.review === "ready"' in STRIP
    assert "Klar til review$/i" not in STRIP
    assert '/klar|ready|pass|godkend/i' not in STRIP


def test_assembly_audition_readiness_uses_canonical_runtime_state() -> None:
    assert "const auditionComplete = auditionReady();" in APP
    assert 'const auditionState = auditionComplete ? "ready" : (a ? "running" : "idle");' in APP
    assert 'const reviewState = auditionComplete ? "ready" : "locked";' in APP
    assert "assemblyBodyState" not in STRIP
    assert "assemblyVoiceState" not in STRIP
    assert "assemblyPersonalityState" not in STRIP
