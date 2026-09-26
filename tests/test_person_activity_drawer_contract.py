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


def test_activity_drawer_consumes_versioned_structured_drift_state_only() -> None:
    for token in (
        "operatorAttentionItems",
        "operatorJobs",
        "operatorLaunches",
        "operator-photoreal-summary",
        "personHud",
    ):
        assert token in JS

    assert "function activitySnapshot(node, expectedKind = null)" in JS
    assert 'node.dataset?.activityStateVersion !== "1"' in JS
    assert "ACTIVITY_KINDS" in JS
    assert "ACTIVITY_STATES" in JS
    assert 'boundedDataset(node, "activityTitle", 200' in JS
    assert 'boundedDataset(node, "activityDetail", 1600' in JS
    assert "if (detail === null || state === null || actionLabel === null) return null;" in JS
    assert 'badge.dataset.stateVersion !== "1"' in JS
    assert 'hud.dataset.stateVersion !== "1"' in JS

    assert "cloneNode(" not in JS
    assert "mirroredRowText" not in JS
    assert "cleanText(" not in JS
    assert "sourceNode.textContent" not in JS
    assert 'operator-photoreal-badge' not in JS
    assert 'operator-photoreal-detail' not in JS
    assert 'personName")?.textContent' not in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS
    assert "MutationObserver" in JS


def test_drift_publishes_bounded_structured_live_activity_snapshots() -> None:
    assert "function boundedActivityText(value, limit)" in OPERATOR_JS
    assert "function publishActivityRow(" in OPERATOR_JS
    assert "function publishPhotorealActivity(" in OPERATOR_JS
    assert 'node.dataset.activityStateVersion = "1";' in OPERATOR_JS
    assert 'node.dataset.activityTitle = boundedActivityText(title, 200);' in OPERATOR_JS
    assert 'node.dataset.activityDetail = boundedActivityText(detail, 1200);' in OPERATOR_JS
    assert 'root.dataset.activityDetail = boundedActivityText(detail, 1600);' in OPERATOR_JS
    assert 'node.dataset.activityUnseen = isNew ? "1" : "0";' in OPERATOR_JS
    assert 'badge.dataset.stateVersion = "1";' in OPERATOR_JS
    assert 'kind: "job"' in OPERATOR_JS
    assert 'kind: "launch"' in OPERATOR_JS
    assert 'kind: "attention"' in OPERATOR_JS
    assert 'root.dataset.activityKind = "photoreal";' in OPERATOR_JS
    photoreal_publish = OPERATOR_JS[
        OPERATOR_JS.index('publishPhotorealActivity({', OPERATOR_JS.index('function renderPhotoreal(')):
        OPERATOR_JS.index('renderServiceWhy("photoreal"', OPERATOR_JS.index('function renderPhotoreal('))
    ]
    assert "summary.textContent" not in photoreal_publish
    assert "detail.textContent" not in photoreal_publish
    assert "pipeline.message" in photoreal_publish
    assert "exavatar.highest_snapshot_epoch" in photoreal_publish


def test_activity_drawer_preserves_existing_attention_navigation_without_new_authority() -> None:
    assert "function mirrorAttention()" in JS
    assert 'node.querySelector("button")' in JS
    assert "sourceAction.isConnected" in JS
    assert "sourceAction.click()" in JS
    assert "snapshot.actionLabel" in JS
    assert "setOpen(false)" in JS
    assert ".person-activity-action" in CSS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_activity_drawer_drills_into_exact_structured_job_or_launch_without_new_authority() -> None:
    assert "function resolveDriftSource(sourceNode)" in JS
    assert "function openDriftSource(sourceNode)" in JS
    assert "activitySnapshot(sourceNode)" in JS
    assert '["job", "launch"].includes(snapshot.kind)' in JS
    assert "candidate?.id === snapshot.id" in JS
    assert '.tab[data-tab="operations"]' in JS
    assert "scrollIntoView" in JS
    assert "activity-focus" in JS
    assert '"Åbn i Drift"' in JS
    assert 'row.dataset.activityKind = "job"' in OPERATOR_JS
    assert 'row.dataset.activityKind = "launch"' in OPERATOR_JS
    assert ".person-activity-drilldown-item" in CSS
    assert ".operator-job-row.activity-focus" in OPERATOR_CSS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_activity_drawer_is_global_control_room_ui() -> None:
    assert "position:fixed" in CSS
    assert "backdrop-filter:blur" in CSS
    assert ".person-activity-drawer.open" in CSS
    assert ".person-activity-item-detail" in CSS
    assert "prefers-reduced-motion" in CSS
