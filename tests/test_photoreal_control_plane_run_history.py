from __future__ import annotations

import json
import os
from pathlib import Path

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

    assert [item["path"] for item in history] == [str(newer.resolve()), str(older.resolve())]
    current = history[0]
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
    }
    assert current["authority"]["historical_execution_authority"] is False

    historical = history[1]
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
