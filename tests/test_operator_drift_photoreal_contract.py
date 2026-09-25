from pathlib import Path


def _js() -> str:
    return Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")


def test_drift_photoreal_monitoring_is_read_only_and_person_scoped() -> None:
    js = _js()

    assert "function currentPersonId()" in js
    assert "/api/v1/people/" in js
    assert "/body/photoreal-control-plane" in js
    assert "/body/photoreal-control-plane/action" not in js
    assert "renderPhotoreal" in js
    assert "MutationObserver" in js


def test_drift_photoreal_attention_is_fail_closed_but_no_run_is_neutral() -> None:
    js = _js()

    assert 'if (state === "no-run" || state === "complete") return null;' in js
    assert 'if (value.exavatar?.busy === true) return null;' in js
    assert 'state === "required"' in js
    assert 'state === "human-review-required"' in js
    assert 'state === "operator-input-required"' in js
    assert 'state === "blocked"' in js
    assert 'photoreal?.ok === false' in js
    assert '"Photoreal / ExAvatar"' in js


def test_drift_does_not_fail_unbound_people_as_photoreal_offline() -> None:
    js = _js()

    assert 'source.kind !== "stash-performer"' in js
    assert '!String(source.performer_id || "").trim()' in js
    assert 'state: "no-run"' in js
    assert 'phase: "not-applicable"' in js
    assert "Personen er ikke bundet til en Stash performer." in js


def test_drift_photoreal_detail_surfaces_live_exavatar_evidence() -> None:
    js = _js()

    for token in (
        "linux_workspace",
        "teacher_work_root",
        "preprocess_completed_count",
        "preprocess_total_count",
        "highest_snapshot_epoch",
        "training_target_epoch",
        "neutral_render_count",
        "active_processes",
        "latest_log",
        "advance_allowed",
        "production_activation",
    ):
        assert token in js


def test_drift_photoreal_run_history_is_read_only_and_marks_continuation() -> None:
    js = _js()
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    assert 'id="operator-photoreal-history"' in html
    assert "Photoreal runhistorik" in html
    assert "historiske runs er evidence-only" in html
    assert "renderPhotorealHistory" in js
    assert "continuation_candidate" in js
    assert "CURRENT" in js
    assert "HISTORY-ONLY" in js
    assert "CONTINUATION" in js
    assert "EVIDENCE" in js
    assert "teacher_input_sha256" in js
    assert ".operator-photoreal-history-row" in css
    assert "/body/photoreal-control-plane/action" not in js
