from __future__ import annotations

import json
from pathlib import Path

from bodyrig.operator_system_ui_api import _operator_launch_result


def _write_result(path: Path, **overrides: object) -> None:
    value = {
        "format": "bodyrig-operator-launch-result",
        "version": 1,
        "launch_id": "system-preflight-" + "a" * 32,
        "pid": 4242,
        "state": "succeeded",
        "exit_code": 0,
        "finished_utc": "2026-09-25T05:15:00Z",
        "duration_seconds": 12.5,
    }
    value.update(overrides)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_operator_launch_result_accepts_exact_terminal_receipt(tmp_path: Path) -> None:
    launch_dir = tmp_path / "system-preflight" / ("system-preflight-" + "a" * 32)
    launch_dir.mkdir(parents=True)
    receipt_path = launch_dir / "launch.json"
    receipt_path.write_text("{}", encoding="utf-8")
    _write_result(launch_dir / "result.json")

    value = _operator_launch_result(
        receipt_path,
        launch_id="system-preflight-" + "a" * 32,
        pid=4242,
    )

    assert value == {
        "state": "succeeded",
        "exit_code": 0,
        "finished_utc": "2026-09-25T05:15:00Z",
        "duration_seconds": 12.5,
    }


def test_operator_launch_result_rejects_identity_state_and_bool_drift(tmp_path: Path) -> None:
    launch_dir = tmp_path / "release" / ("release-" + "b" * 32)
    launch_dir.mkdir(parents=True)
    receipt_path = launch_dir / "launch.json"
    receipt_path.write_text("{}", encoding="utf-8")
    result_path = launch_dir / "result.json"

    cases = (
        {"launch_id": "other-launch"},
        {"pid": 9999},
        {"version": True},
        {"pid": True},
        {"exit_code": True},
        {"duration_seconds": True},
        {"state": "succeeded", "exit_code": 7},
        {"state": "failed", "exit_code": 0},
        {"state": "unknown"},
        {"finished_utc": ""},
        {"duration_seconds": -1},
    )
    for overrides in cases:
        values = {
            "launch_id": "release-" + "b" * 32,
            "pid": 4242,
            **overrides,
        }
        _write_result(result_path, **values)
        assert (
            _operator_launch_result(
                receipt_path,
                launch_id="release-" + "b" * 32,
                pid=4242,
            )
            is None
        ), overrides


def test_operator_launch_source_records_completion_without_shell_authority() -> None:
    source = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")

    assert "process.wait()" in source
    assert '"bodyrig-operator-launch-result"' in source
    assert '"state": "succeeded" if exit_code == 0 else "failed"' in source
    assert '"exit_code": exit_code' in source
    assert '"finished_utc": finished_utc' in source
    assert '"duration_seconds": round(duration, 3)' in source
    assert "threading.Thread(" in source
    assert "daemon=True" in source
    assert "os.replace(temp, path)" in source
    assert "shell=False" in source
