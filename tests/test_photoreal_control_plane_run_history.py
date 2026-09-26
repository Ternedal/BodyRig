from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bodyrig import photoreal_control_plane_ui as control


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run(root: Path, name: str, performer_id: str, stamp: int) -> Path:
    run = root / "photoreal-v2" / "overnight" / name
    run.mkdir(parents=True)
    _write_json(run / "source-resume-receipt.json", {"performer_id": performer_id})
    os.utime(run, (stamp, stamp))
    return run


def test_photoreal_history_marks_only_latest_valid_run_as_continuation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    older = _run(
        tmp_path,
        "performer-42-20260920-100000-resume1",
        "42",
        1000,
    )
    newer = _run(
        tmp_path,
        "performer-42-20260920-110000-resume2",
        "42",
        2000,
    )
    _run(
        tmp_path,
        "performer-42-20260920-120000-resume3",
        "99",
        3000,
    )

    _write_json(
        newer / "identity-calibration.json",
        {
            "format": "bodyrig-photoreal-identity-calibration",
            "version": 1,
            "target_performer_id": "42",
            "identity_matching_authorized": True,
        },
    )
    custom_teacher = tmp_path / "custom-current-teacher"
    custom_teacher.mkdir()
    _write_json(
        custom_teacher / "teacher-input.json",
        {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "performer_id": "42",
            "teacher_input_sha256": "a" * 64,
        },
    )
    _write_json(
        custom_teacher / "exavatar-teacher-config.json",
        {
            "command": [
                "python",
                "--workspace-root",
                "/opt/bodyrig-exavatar/workspaces/bodyrig-42-current",
                "--distribution",
                "Ubuntu-22.04",
                "--wsl-exe",
                "wsl.exe",
                "--linux-python",
                "/opt/bodyrig-exavatar/bin/python",
            ]
        },
    )
    _write_json(
        custom_teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json",
        {"ok": True},
    )

    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        control,
        "_probe_wsl",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("history must not run a second WSL probe")
        ),
    )
    history = control._photoreal_run_history(
        "42",
        newer,
        current_teacher_root=custom_teacher,
        current_exavatar={
            "phase": "training",
            "busy": True,
            "highest_snapshot_epoch": 3,
            "activity": {
                "state": "active",
                "stalled_suspected": False,
                "reason": None,
                "latest_log_age_seconds": 30.0,
                "oldest_active_process_age_seconds": 600.0,
                "stale_after_seconds": 1800.0,
            },
            "preprocess_completed_count": 9,
            "preprocess_total_count": 9,
            "neutral_render_count": 0,
            "latest_log": {
                "name": "train.log",
                "modified_utc": "2026-09-25T14:00:00Z",
            },
        },
        limit=8,
    )

    assert sorted(item["role"] for item in history) == [
        "current-canonical-run",
        "history-only",
        "rejected",
    ]
    rejected = next(item for item in history if item["role"] == "rejected")
    assert rejected["continuation_candidate"] is False
    assert rejected["integrity_valid"] is False
    assert "does not match expected" in rejected["rejection_reason"]
    assert rejected["authority"]["historical_execution_authority"] is False

    current = next(item for item in history if item["role"] == "current-canonical-run")
    assert current["current"] is True
    assert current["continuation_candidate"] is True
    assert current["role"] == "current-canonical-run"
    assert current["calibration_state"] == "valid"
    assert current["identity_matching_authorized"] is True
    assert current["teacher_root"] == str(custom_teacher.resolve())
    assert current["teacher_input_valid"] is True
    assert current["teacher_input_sha256"] == "a" * 64
    assert current["teacher_config_present"] is True
    assert current["teacher_manifest_present"] is True
    assert current["workspace"] == "/opt/bodyrig-exavatar/workspaces/bodyrig-42-current"
    assert current["live_evidence"] == {
        "scope": "current-only",
        "phase": "training",
        "busy": True,
        "highest_snapshot_epoch": 3,
        "preprocess_completed_count": 9,
        "preprocess_total_count": 9,
        "neutral_render_count": 0,
        "latest_log_name": "train.log",
        "latest_log_modified_utc": "2026-09-25T14:00:00Z",
        "activity": {
            "state": "active",
            "stalled_suspected": False,
            "reason": None,
            "latest_log_age_seconds": 30.0,
            "oldest_active_process_age_seconds": 600.0,
            "stale_after_seconds": 1800.0,
        },
    }
    assert current["authority"]["historical_execution_authority"] is False

    historical = next(item for item in history if item["role"] == "history-only")
    assert historical["current"] is False
    assert historical["continuation_candidate"] is False
    assert historical["role"] == "history-only"
    assert historical["live_evidence"] is None
    assert historical["authority"]["continuation_candidate"] is False

def test_photoreal_history_rejects_semantically_wrong_teacher_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _run(
        tmp_path,
        "performer-42-20260920-130000-resume4",
        "42",
        4000,
    )
    teacher = Path(str(run.resolve()) + "-teacher")
    teacher.mkdir()
    _write_json(
        teacher / "teacher-input.json",
        {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "performer_id": "99",
            "teacher_input_sha256": "b" * 64,
        },
    )

    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    history = control._photoreal_run_history("42", run)

    assert len(history) == 1
    assert history[0]["teacher_input_present"] is True
    assert history[0]["teacher_input_valid"] is False
    assert history[0]["teacher_input_sha256"] is None


def test_photoreal_history_rejects_bool_versions_and_keeps_authority_false(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _run(
        tmp_path,
        "performer-42-20260920-140000-resume5",
        "42",
        5000,
    )
    _write_json(
        run / "identity-calibration.json",
        {
            "format": "bodyrig-photoreal-identity-calibration",
            "version": True,
            "target_performer_id": "42",
            "identity_matching_authorized": True,
        },
    )
    teacher = Path(str(run.resolve()) + "-teacher")
    teacher.mkdir()
    _write_json(
        teacher / "teacher-input.json",
        {
            "format": "bodyrig-photoreal-teacher-input",
            "version": True,
            "performer_id": "42",
            "teacher_input_sha256": "c" * 64,
        },
    )

    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    history = control._photoreal_run_history("42", run)

    assert len(history) == 1
    item = history[0]
    assert item["calibration_state"] == "invalid"
    assert item["identity_matching_authorized"] is False
    assert item["teacher_input_valid"] is False
    assert item["teacher_input_sha256"] is None
    assert item["authority"]["historical_execution_authority"] is False
    assert item["authority"]["production_activation"] is False


def test_run_history_ignores_entry_removed_after_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vanished = tmp_path / "photoreal-v2" / "overnight" / "performer-42-vanished"
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        control,
        "list_performer_runs",
        lambda *_args, **_kwargs: [vanished],
    )

    history = control._photoreal_run_history("42", vanished)

    assert history == []


def test_run_discovery_does_not_trust_symlinked_performer_declaration(
    tmp_path: Path,
) -> None:
    from bodyrig import photoreal_calibration_ui as calibration

    run = tmp_path / "photoreal-v2" / "overnight" / "performer-42-symlink"
    run.mkdir(parents=True)
    external = tmp_path / "external-performer.json"
    _write_json(external, {"performer_id": "42"})
    declaration = run / "source-resume-receipt.json"
    try:
        declaration.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation is unavailable on this CI host")

    assert calibration._declared_performer_id(run) is None
    assert calibration.list_performer_runs(tmp_path, "42") == []

def test_no_valid_run_still_surfaces_rejected_candidate_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rejected = _run(
        tmp_path,
        "performer-42-20260920-150000-resume6",
        "99",
        6000,
    )
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)

    history = control._photoreal_run_history("42", None)

    assert len(history) == 1
    assert history[0]["path"] == str(rejected.absolute())
    assert history[0]["role"] == "rejected"
    assert history[0]["integrity_valid"] is False
    assert history[0]["continuation_candidate"] is False
    assert history[0]["authority"]["production_activation"] is False

def test_newest_rejected_candidate_sorts_ahead_of_current_valid_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _run(
        tmp_path,
        "performer-42-20260920-160000-resume7",
        "42",
        7000,
    )
    rejected = _run(
        tmp_path,
        "performer-42-20260920-170000-resume8",
        "99",
        8000,
    )
    os.utime(current, (7000, 7000))
    os.utime(rejected, (8000, 8000))
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)

    history = control._photoreal_run_history("42", current)

    assert history[0]["role"] == "rejected"
    assert history[0]["integrity_valid"] is False
    assert history[1]["role"] == "current-canonical-run"
    assert history[1]["continuation_candidate"] is True

