from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from bodyrig.operator_launch_runner import OperatorLaunchRunnerError, _load_request
import bodyrig.operator_system_ui_api as operator_ui
from bodyrig.operator_system_ui_api import (
    _operator_launch_heartbeat,
    _operator_launch_receipt,
    _operator_launch_result,
)


def _write_supervisor_launch(
    launch_dir: Path,
    *,
    launch_id: str,
    category: str,
    pid: int = 4242,
) -> tuple[Path, str]:
    launch_dir.mkdir(parents=True, exist_ok=True)
    request_path = launch_dir / "request.json"
    request = {
        "format": "bodyrig-operator-launch-request",
        "version": 1,
        "launch_id": launch_id,
        "category": category,
        "context": {"gate": "p1-static-teacher"},
        "pwsh_path": sys.executable,
        "command": "Write-Host test",
        "cwd": str(launch_dir),
        "started_utc": "2026-09-25T07:30:00Z",
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    receipt = {
        "format": "bodyrig-operator-launch",
        "version": 1,
        "launch_id": launch_id,
        "category": category,
        "pid": pid,
        "process_role": "restart-safe-supervisor",
        "started_utc": "2026-09-25T07:30:00Z",
        "log_path": str((launch_dir / "operator.log").resolve()),
        "request_path": str(request_path.resolve()),
        "request_sha256": request_sha256,
        "result_path": str((launch_dir / "result.json").resolve()),
        "context": {"gate": "p1-static-teacher"},
    }
    receipt_path = launch_dir / "launch.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path, request_sha256


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


def test_operator_launch_heartbeat_requires_exact_identity_and_fresh_file(tmp_path: Path) -> None:
    launch_id = "system-preflight-" + "h" * 32
    launch_dir = tmp_path / "system-preflight" / launch_id
    launch_dir.mkdir(parents=True)
    receipt_path = launch_dir / "launch.json"
    receipt_path.write_text("{}", encoding="utf-8")
    request_sha256 = "a" * 64
    heartbeat_path = launch_dir / "heartbeat.json"
    heartbeat = {
        "format": "bodyrig-operator-launch-heartbeat",
        "version": 1,
        "launch_id": launch_id,
        "pid": 4242,
        "child_pid": 5252,
        "request_sha256": request_sha256,
        "heartbeat_utc": "2026-09-25T07:30:00Z",
    }
    heartbeat_path.write_text(json.dumps(heartbeat), encoding="utf-8")

    value = _operator_launch_heartbeat(
        receipt_path,
        launch_id=launch_id,
        pid=4242,
        request_sha256=request_sha256,
        max_age_seconds=15.0,
    )
    assert value is not None
    assert value["child_pid"] == 5252
    assert value["heartbeat_utc"] == "2026-09-25T07:30:00Z"
    assert value["heartbeat_age_seconds"] >= 0

    heartbeat_path.write_text(
        json.dumps({**heartbeat, "request_sha256": "b" * 64}),
        encoding="utf-8",
    )
    assert _operator_launch_heartbeat(
        receipt_path,
        launch_id=launch_id,
        pid=4242,
        request_sha256=request_sha256,
    ) is None

    heartbeat_path.write_text(json.dumps(heartbeat), encoding="utf-8")
    stale = time.time() - 60
    os.utime(heartbeat_path, (stale, stale))
    assert _operator_launch_heartbeat(
        receipt_path,
        launch_id=launch_id,
        pid=4242,
        request_sha256=request_sha256,
        max_age_seconds=15.0,
    ) is None


def test_restart_safe_supervisor_never_uses_pid_alone_as_running_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch_id = "photoreal-" + "c" * 32
    launch_dir = tmp_path / "operator-launches" / "photoreal" / launch_id
    _receipt_path, request_sha256 = _write_supervisor_launch(
        launch_dir,
        launch_id=launch_id,
        category="photoreal",
    )
    monkeypatch.setattr(operator_ui, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(operator_ui, "_pid_running", lambda pid: pid == 4242)

    without_heartbeat = operator_ui._operator_launches()
    assert without_heartbeat[0]["state"] == "unknown"
    assert without_heartbeat[0]["running"] is False
    assert without_heartbeat[0]["heartbeat_fresh"] is False

    heartbeat = {
        "format": "bodyrig-operator-launch-heartbeat",
        "version": 1,
        "launch_id": launch_id,
        "pid": 4242,
        "child_pid": 5252,
        "request_sha256": request_sha256,
        "heartbeat_utc": "2026-09-25T07:30:02Z",
    }
    (launch_dir / "heartbeat.json").write_text(json.dumps(heartbeat), encoding="utf-8")
    with_heartbeat = operator_ui._operator_launches()
    assert with_heartbeat[0]["state"] == "running"
    assert with_heartbeat[0]["running"] is True
    assert with_heartbeat[0]["heartbeat_fresh"] is True
    assert with_heartbeat[0]["child_pid"] == 5252


def test_operator_launch_receipt_accepts_exact_supervisor_and_legacy_receipts(
    tmp_path: Path,
) -> None:
    supervisor_id = "photoreal-" + "a" * 32
    supervisor_dir = tmp_path / "photoreal" / supervisor_id
    receipt_path, request_sha256 = _write_supervisor_launch(
        supervisor_dir,
        launch_id=supervisor_id,
        category="photoreal",
    )
    receipt, error = _operator_launch_receipt(receipt_path)
    assert error is None
    assert receipt is not None
    assert receipt["launch_id"] == supervisor_id
    assert receipt["request_sha256"] == request_sha256
    assert receipt["process_role"] == "restart-safe-supervisor"

    legacy_id = "release-" + "b" * 32
    legacy_dir = tmp_path / "release" / legacy_id
    legacy_dir.mkdir(parents=True)
    legacy_path = legacy_dir / "launch.json"
    legacy_path.write_text(
        json.dumps(
            {
                "format": "bodyrig-operator-launch",
                "version": 1,
                "launch_id": legacy_id,
                "category": "release",
                "pid": 3131,
                "started_utc": "2026-09-24T20:00:00Z",
                "context": {"gate": "review"},
            }
        ),
        encoding="utf-8",
    )
    legacy, legacy_error = _operator_launch_receipt(legacy_path)
    assert legacy_error is None
    assert legacy is not None
    assert legacy["process_role"] == ""
    assert legacy["request_sha256"] == ""


def test_operator_launch_receipt_rejects_path_identity_and_request_tamper(
    tmp_path: Path,
) -> None:
    launch_id = "system-preflight-" + "c" * 32
    launch_dir = tmp_path / "system-preflight" / launch_id
    receipt_path, _request_sha256 = _write_supervisor_launch(
        launch_dir,
        launch_id=launch_id,
        category="system-preflight",
    )
    original = json.loads(receipt_path.read_text(encoding="utf-8"))

    cases = (
        ({**original, "format": "wrong-format"}, "format"),
        ({**original, "version": True}, "version"),
        ({**original, "pid": True}, "PID"),
        ({**original, "category": "photoreal"}, "category"),
        ({**original, "launch_id": "system-preflight-" + "d" * 32}, "id"),
        ({**original, "process_role": "mystery-role"}, "process role"),
        ({**original, "request_path": str((tmp_path / "other.json").resolve())}, "request path"),
        ({**original, "log_path": str((tmp_path / "other.log").resolve())}, "log path"),
        ({**original, "result_path": str((tmp_path / "other-result.json").resolve())}, "result path"),
    )
    for value, expected_error in cases:
        receipt_path.write_text(json.dumps(value), encoding="utf-8")
        receipt, error = _operator_launch_receipt(receipt_path)
        assert receipt is None
        assert error is not None and expected_error.lower() in error.lower()

    receipt_path.write_text(json.dumps(original), encoding="utf-8")
    request_path = launch_dir / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request_path.write_text(json.dumps({**request, "command": "tampered"}), encoding="utf-8")
    receipt, error = _operator_launch_receipt(receipt_path)
    assert receipt is None
    assert error is not None and "SHA-256" in error

    semantic_request = {**request, "context": {"gate": "different-gate"}}
    request_path.write_text(json.dumps(semantic_request), encoding="utf-8")
    rewritten = {
        **original,
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
    }
    receipt_path.write_text(json.dumps(rewritten), encoding="utf-8")
    receipt, error = _operator_launch_receipt(receipt_path)
    assert receipt is None
    assert error is not None and "context" in error.lower()


def test_operator_launches_surface_invalid_start_receipt_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_id = "release-" + "e" * 32
    valid_dir = tmp_path / "operator-launches" / "release" / valid_id
    valid_dir.mkdir(parents=True)
    (valid_dir / "launch.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-operator-launch",
                "version": 1,
                "launch_id": valid_id,
                "category": "release",
                "pid": 1111,
                "started_utc": "2026-09-25T09:00:00Z",
                "context": {"gate": "review"},
            }
        ),
        encoding="utf-8",
    )

    invalid_id = "photoreal-" + "f" * 32
    invalid_dir = tmp_path / "operator-launches" / "photoreal" / invalid_id
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "launch.json").write_text(
        json.dumps(
            {
                "format": "wrong",
                "version": 1,
                "launch_id": invalid_id,
                "category": "photoreal",
                "pid": 2222,
                "started_utc": "2026-09-20T09:00:00Z",
                "context": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(operator_ui, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(operator_ui, "_pid_running", lambda _pid: False)
    values = operator_ui._operator_launches(limit=1)
    assert len(values) == 1
    assert values[0]["launch_id"] == invalid_id
    assert values[0]["state"] == "unknown"
    assert values[0]["integrity_valid"] is False
    assert "format" in str(values[0]["integrity_error"]).lower()


def test_supervisor_request_is_hash_bound_before_execution(tmp_path: Path) -> None:
    launch_id = "system-preflight-" + "f" * 32
    launch_dir = tmp_path / launch_id
    launch_dir.mkdir()
    request_path = launch_dir / "request.json"
    request = {
        "format": "bodyrig-operator-launch-request",
        "version": 1,
        "launch_id": launch_id,
        "category": "system-preflight",
        "context": {"action": "run-rig-preflight"},
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

    assert "child.poll()" in runner
    assert "_write_heartbeat(" in runner
    assert '"bodyrig-operator-launch-heartbeat"' in runner
    assert "time.sleep(2.0)" in runner
    assert "Operator launch heartbeat write failed; supervision continues" in runner
    assert '"bodyrig-operator-launch-result"' in runner
    assert '"state": "succeeded" if exit_code == 0 else "failed"' in runner
    assert '"exit_code": exit_code' in runner
    assert '"finished_utc": finished_utc' in runner
    assert '"duration_seconds": round(duration, 3)' in runner
    assert '"request_sha256": request["request_sha256"]' in runner
    assert 'result["child_pid"] = child_pid' in runner
    assert '"process_role": "restart-safe-supervisor"' in runner
    assert "receipt_path = path.parent / \"launch.json\"" in runner
    assert runner.index("_atomic_write_json(receipt_path, receipt)") < runner.index("child = subprocess.Popen(")
    assert "os.replace(temp, path)" in runner
    assert "shell=False" in runner
