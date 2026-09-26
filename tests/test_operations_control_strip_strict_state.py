from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
STRIP = (ROOT / "bodyrig" / "ui" / "operations_control_strip.js").read_text(encoding="utf-8")


def test_drift_publishes_versioned_operations_state_from_structured_authority() -> None:
    assert "function publishOperationsControlChecking()" in CONTROL
    assert "function publishOperationsControlState(serviceResults, jobs, launches, digitalTwin)" in CONTROL
    assert 'host.dataset.stateVersion = "1";' in CONTROL
    assert "serviceResultFresh(item)" in CONTROL
    assert "serviceHealthy(item.key, item.value)" in CONTROL
    assert "!jobAttention(jobs)" in CONTROL
    assert "!launchAttention(launches)" in CONTROL
    assert "twinValue.digital_twin_ready === true" in CONTROL
    assert "twinValue.production_activation === true" in CONTROL
    assert "const attentionCount = activeAttentionKeys.size;" in CONTROL
    assert "publishOperationsControlChecking();" in CONTROL
    assert "publishOperationsControlState(serviceResults, jobs, launches, digitalTwin);" in CONTROL
    assert CONTROL.index("renderAttentionInbox(serviceResults, jobs, launches, photoreal, digitalTwin);") < CONTROL.index(
        "publishOperationsControlState(serviceResults, jobs, launches, digitalTwin);"
    )


def test_operations_strip_fails_closed_without_valid_versioned_snapshot() -> None:
    assert 'root.dataset.stateVersion !== "1"' in STRIP
    assert 'health: new Set(["ready", "blocked", "checking"])' in STRIP
    assert 'attention: new Set(["ready", "attention", "checking"])' in STRIP
    assert 'execution: new Set(["ready", "attention", "checking"])' in STRIP
    assert 'twin: new Set(["ready", "blocked", "unknown", "checking"])' in STRIP
    assert 'priority: new Set(["ready", "attention", "blocked", "checking"])' in STRIP
    assert 'setChip("operationsControlHealth", "Ukendt", false);' in STRIP
    assert 'next.textContent = "Afventer authoritative Drift-snapshot…";' in STRIP
    assert "badState" not in STRIP
    assert "operatorSummary" not in STRIP
    assert "operatorJobsStatus" not in STRIP
    assert "operatorLaunchesStatus" not in STRIP
    assert "fetch(" not in STRIP
    assert "POST" not in STRIP


def test_operations_strip_is_navigation_only_after_state_handoff() -> None:
    for target in (
        "operatorRefresh",
        "operatorAttentionItems",
        "operatorJobs",
        "operator-digital-twin-stages",
    ):
        assert target in STRIP
    assert "scrollIntoView" in STRIP
    assert "new MutationObserver(refresh).observe(root, { attributes: true });" in STRIP
