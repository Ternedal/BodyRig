from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.css").read_text(encoding="utf-8")


def test_drift_has_operator_attention_inbox() -> None:
    assert 'id="operatorAttentionStatus"' in HTML
    assert 'id="operatorAttentionBadge"' in HTML
    assert 'id="operatorAttentionItems"' in HTML
    assert "renderAttentionInbox(serviceResults, jobs, launches, photoreal, digitalTwin)" in JS
    assert ".operator-attention-item" in CSS


def test_attention_inbox_reuses_existing_navigation_and_authority() -> None:
    start = JS.index("function renderAttentionInbox(")
    end = JS.index("async function refresh(", start)
    inbox = JS[start:end]
    assert "openJobPerson(job)" in inbox
    assert '.tab[data-tab="body"]' in inbox
    assert "scrollToOperatorTarget" in inbox
    assert "fetch(" not in inbox
    assert "api(" not in inbox
    assert 'method: "POST"' not in inbox
    assert "/action" not in inbox


def test_attention_inbox_prioritizes_operator_input_and_current_authority_failures() -> None:
    start = JS.index("function renderAttentionInbox(")
    end = JS.index("async function refresh(", start)
    inbox = JS[start:end]
    assert "ACTION_JOB_STATES" in inbox
    assert "stalled_suspected" in inbox
    assert "digital_twin_ready" in inbox
    assert '["failed", "unknown"]' in inbox
    assert "serviceBlockers" in inbox
    assert "serviceResultFresh" in inbox
