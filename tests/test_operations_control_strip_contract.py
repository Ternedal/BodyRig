from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "operations_control_strip.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "operations_control_strip.css").read_text(encoding="utf-8")

def test_operations_tab_has_control_strip() -> None:
    for token in ('id="operationsControlStrip"','id="operationsControlHealth"','id="operationsControlAttention"','id="operationsControlExecution"','id="operationsControlTwin"','id="operationsControlNext"'):
        assert token in HTML
    assert '<script src="/ui/operations_control_strip.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/operations_control_strip.css">' in HTML

def test_operations_strip_reuses_structured_drift_state() -> None:
    assert "operationsControlStrip" in JS
    assert 'root.dataset.stateVersion !== "1"' in JS
    assert "structuredState" in JS
    assert "readField" in JS
    assert "MutationObserver" in JS
    assert "attributes: true" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert "operatorSummary" not in JS
    assert "operatorJobsStatus" not in JS
    assert "operatorLaunchesStatus" not in JS

def test_operations_strip_is_navigation_only() -> None:
    assert "scrollIntoView" in JS
    assert "operatorJobs" in JS
    assert "operator-digital-twin-stages" in JS
    assert "position:sticky" in CSS
