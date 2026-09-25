from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import bodyrig.photoreal_control_plane_ui as control


def _latest(age_seconds: float) -> dict[str, float]:
    return {
        "modified_unix": datetime.now(tz=timezone.utc).timestamp() - age_seconds,
    }


def test_active_exavatar_with_recent_log_is_not_stalled() -> None:
    value = control._exavatar_activity(
        ["123 train.py"],
        _latest(60),
        600,
    )

    assert value["state"] == "active"
    assert value["stalled_suspected"] is False
    assert value["recent_log"] is True
    assert value["latest_log_age_seconds"] is not None


def test_active_exavatar_with_stale_log_is_suspected_stall() -> None:
    value = control._exavatar_activity(
        ["123 train.py"],
        _latest(control._EXAVATAR_ACTIVITY_STALE_SECONDS + 120),
        2400,
    )

    assert value["state"] == "stalled-suspected"
    assert value["stalled_suspected"] is True
    assert value["recent_log"] is False
    assert "ikke opdateret seneste log" in str(value["reason"])


def test_new_active_process_is_not_stalled_by_older_previous_stage_log() -> None:
    value = control._exavatar_activity(
        ["123 train.py"],
        _latest(control._EXAVATAR_ACTIVITY_STALE_SECONDS + 3600),
        120,
    )

    assert value["state"] == "active"
    assert value["stalled_suspected"] is False
    assert value["recent_log"] is False
    assert value["oldest_active_process_age_seconds"] == 120


def test_old_active_exavatar_without_log_is_suspected_stall() -> None:
    value = control._exavatar_activity(
        ["123 run_mmpose.py"],
        None,
        control._EXAVATAR_ACTIVITY_STALE_SECONDS + 120,
    )

    assert value["state"] == "stalled-suspected"
    assert value["stalled_suspected"] is True
    assert value["latest_log_age_seconds"] is None
    assert "uden log-evidence" in str(value["reason"])


def test_idle_workspace_never_becomes_stall_from_old_log() -> None:
    value = control._exavatar_activity(
        [],
        _latest(control._EXAVATAR_ACTIVITY_STALE_SECONDS + 3600),
        None,
    )

    assert value["state"] == "idle"
    assert value["stalled_suspected"] is False
    assert value["recent_log"] is False


def test_stall_warning_never_releases_busy_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        control,
        "_teacher_transport",
        lambda _root: {
            "workspace": "/opt/bodyrig-exavatar/workspaces/test",
            "distribution": "Ubuntu-22.04",
            "wsl_exe": "wsl.exe",
            "linux_python": "/opt/bodyrig-exavatar/bin/python",
            "source": "test",
        },
    )
    monkeypatch.setattr(
        control,
        "_probe_wsl",
        lambda _transport: {
            "available": True,
            "active_processes": ["123 train.py"],
            "oldest_active_process_age_seconds": 2400.0,
            "latest_log": _latest(control._EXAVATAR_ACTIVITY_STALE_SECONDS + 120),
            "completed_stages": [],
            "highest_snapshot_epoch": 2,
            "neutral_render_count": 0,
        },
    )

    value = control._live_exavatar(tmp_path)

    assert value["busy"] is True
    assert value["phase"] == "training"
    assert value["activity"]["stalled_suspected"] is True
    assert value["activity"]["state"] == "stalled-suspected"
