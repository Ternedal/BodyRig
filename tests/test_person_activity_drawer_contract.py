from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_activity_drawer.css").read_text(encoding="utf-8")
OPERATOR_JS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.js").read_text(encoding="utf-8")
OPERATOR_CSS = (ROOT / "bodyrig" / "ui" / "operator_control_plane.css").read_text(encoding="utf-8")


def test_person_studio_has_global_live_activity_drawer() -> None:
    for token in (
        'id="personActivityDrawer"',
        'id="personActivityToggle"',
        'id="personActivityAttention"',
        'id="personActivityJobs"',
        'id="personActivityLaunches"',
        'id="personActivityPhotoreal"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_activity_drawer.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_activity_drawer.css">' in HTML


def test_activity_drawer_reuses_rendered_drift_state_only() -> None:
    for token in (
        "operatorAttentionItems",
        "operatorJobs",
        "operatorLaunches",
        "operator-photoreal-badge",
        "operator-photoreal-summary",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert "MutationObserver" in JS


def test_activity_drawer_is_global_control_room_ui() -> None:
    assert "position:fixed" in CSS
    assert "backdrop-filter:blur" in CSS
    assert ".person-activity-drawer.open" in CSS
    assert "prefers-reduced-motion" in CSS


def test_activity_drawer_preserves_existing_attention_navigation_without_new_authority() -> None:
    assert "function mirrorAttention()" in JS
    assert 'sourceNode.querySelector("button")' in JS
    assert "sourceAction.isConnected" in JS
    assert "sourceAction.click()" in JS
    assert "setOpen(false)" in JS
    assert ".person-activity-action" in CSS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_activity_drawer_drills_into_exact_rendered_job_or_launch_without_new_authority() -> None:
    assert "function mirroredRowText(sourceNode)" in JS
    assert 'copy.querySelectorAll("button, audio, progress, details")' in JS
    assert "function resolveDriftSource(sourceNode)" in JS
    assert "function openDriftSource(sourceNode)" in JS
    assert '.tab[data-tab="operations"]' in JS
    assert "scrollIntoView" in JS
    assert "activity-focus" in JS
    assert '"Åbn i Drift"' in JS
    assert "sourceNode?.dataset?.activityKind" in JS
    assert "sourceNode?.dataset?.activityId" in JS
    assert 'row.dataset.activityKind = "job"' in OPERATOR_JS
    assert 'row.dataset.activityKind = "launch"' in OPERATOR_JS
    assert "row.dataset.activityId" in OPERATOR_JS
    assert ".person-activity-drilldown-item" in CSS
    assert ".operator-job-row.activity-focus" in OPERATOR_CSS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
