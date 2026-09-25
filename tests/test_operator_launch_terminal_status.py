from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from bodyrig.operator_launch_runner import OperatorLaunchRunnerError, _load_request
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
        "child_pid": None,
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
        {"child_pid": True},
        {"child_pid": 0},
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


def test_operator_launch_result_binds_new_receipts_to_request_sha(tmp_path: Path) -> None:
    launch_id = "photoreal-" + "c" * 32
    launch_dir = tmp_path / "photoreal" / launch_id
    launch_dir.mkdir(parents=True)
    receipt_path = launch_dir / "launch.json"
    receipt_path.write_text("{}", encoding="utf-8")
    request_sha256 = "d" * 64

    _write_result(
        launch_dir / "result.json",
        launch_id=launch_id,
        request_sha256=request_sha256,
        child_pid=5151,
    )
    value = _operator_launch_result(
        receipt_path,
        launch_id=launch_id,
        pid=4242,
        request_sha256=request_sha256,
    )
    assert value is not None
    assert value["child_pid"] == 5151

    _write_result(
        launch_dir / "result.json",
        launch_id=launch_id,
        request_sha256="e" * 64,
    )
    assert _operator_launch_result(
        receipt_path,
        launch_id=launch_id,
        pid=4242,
        request_sha256=request_sha256,
    ) is None


def test_supervisor_request_is_hash_bound_before_execution(tmp_path: Path) -> None:
    launch_id = "system-preflight-" + "f" * 32
    launch_dir = tmp_path / launch_id
    launch_dir.mkdir()
    request_path = launch_dir / "request.json"
    request = {
        "format": "bodyrig-operator-launch-request",
        "version": 1,
        "launch_id": launch_id,
        "pwsh_path": sys.executable,
        "command": "Write-Host test",
        "cwd": str(tmp_path),
        "started_utc": "2026-09-25T07:00:00Z",
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    digest = hashlib.sha256(request_path.read_bytes()).hexdigest()

    loaded = _load_request(request_path, digest)
    assert loaded["launch_id"] == launch_id
    assert loaded["request_sha256"] == digest

    request_path.write_text(json.dumps({**request, "command": "tampered"}), encoding="utf-8")
    with pytest.raises(OperatorLaunchRunnerError, match="SHA-256 changed"):
        _load_request(request_path, digest)


def test_operator_launch_source_uses_restart_safe_supervisor_without_shell_authority() -> None:
    launcher = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")
    runner = Path("bodyrig/operator_launch_runner.py").read_text(encoding="utf-8")

    assert '"bodyrig-operator-launch-request"' in launcher
    assert "request_sha256" in launcher
    assert 'process_role": "restart-safe-supervisor"' in launcher
    assert "operator_launch_runner.py" in launcher
    assert "start_new_session=os.name != \"nt\"" in launcher
    assert "threading.Thread(" not in launcher
    assert "daemon=True" not in launcher
    assert "shell=False" in launcher

    assert "child.wait()" in runner
    assert '"bodyrig-operator-launch-result"' in runner
    assert '"state": "succeeded" if exit_code == 0 else "failed"' in runner
    assert '"exit_code": exit_code' in runner
    assert '"finished_utc": finished_utc' in runner
    assert '"duration_seconds": round(duration, 3)' in runner
    assert '"request_sha256": request["request_sha256"]' in runner
    assert 'result["child_pid"] = child_pid' in runner
    assert "os.replace(temp, path)" in runner
    assert "shell=False" in runner
