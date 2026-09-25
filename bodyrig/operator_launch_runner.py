from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class OperatorLaunchRunnerError(RuntimeError):
    pass


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(
            json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def _load_request(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not _SHA256_RE.fullmatch(str(expected_sha256 or "")):
        raise OperatorLaunchRunnerError("Operator launch request SHA-256 is invalid")
    if not path.is_file() or path.is_symlink():
        raise OperatorLaunchRunnerError("Operator launch request is missing or not a regular file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OperatorLaunchRunnerError(f"Could not read operator launch request: {exc}") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise OperatorLaunchRunnerError("Operator launch request SHA-256 changed before supervisor start")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorLaunchRunnerError("Operator launch request is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OperatorLaunchRunnerError("Operator launch request must be a JSON object")
    if value.get("format") != "bodyrig-operator-launch-request":
        raise OperatorLaunchRunnerError("Operator launch request format is invalid")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise OperatorLaunchRunnerError("Operator launch request version is invalid")

    launch_id = str(value.get("launch_id") or "").strip()
    if not launch_id or path.parent.name != launch_id:
        raise OperatorLaunchRunnerError("Operator launch request identity does not match its directory")
    category = str(value.get("category") or "").strip()
    if not category or any(
        ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for ch in category.lower()
    ):
        raise OperatorLaunchRunnerError("Operator launch request category is invalid")
    context = value.get("context")
    if not isinstance(context, dict):
        raise OperatorLaunchRunnerError("Operator launch request context must be an object")
    command = str(value.get("command") or "").strip()
    if not command:
        raise OperatorLaunchRunnerError("Operator launch request command is empty")
    pwsh_path = str(value.get("pwsh_path") or "").strip()
    if not pwsh_path or not Path(pwsh_path).is_file():
        raise OperatorLaunchRunnerError("Operator launch PowerShell executable is unavailable")
    cwd = Path(str(value.get("cwd") or "")).expanduser()
    if not cwd.is_dir():
        raise OperatorLaunchRunnerError("Operator launch working directory is unavailable")
    started_utc = str(value.get("started_utc") or "").strip()
    if not started_utc:
        raise OperatorLaunchRunnerError("Operator launch request has no start timestamp")
    return {
        "launch_id": launch_id,
        "category": category,
        "context": dict(context),
        "command": command,
        "pwsh_path": pwsh_path,
        "cwd": str(cwd.resolve()),
        "started_utc": started_utc,
        "request_sha256": actual_sha256,
    }


def _write_heartbeat(
    path: Path,
    *,
    launch_id: str,
    supervisor_pid: int,
    child_pid: int,
    request_sha256: str,
) -> None:
    _atomic_write_json(
        path,
        {
            "format": "bodyrig-operator-launch-heartbeat",
            "version": 1,
            "launch_id": launch_id,
            "pid": supervisor_pid,
            "child_pid": child_pid,
            "request_sha256": request_sha256,
            "heartbeat_utc": _utc_now(),
        },
    )


def run_request(path: Path, expected_sha256: str) -> int:
    request = _load_request(path, expected_sha256)
    log_path = path.parent / "operator.log"
    receipt_path = path.parent / "launch.json"
    result_path = path.parent / "result.json"
    heartbeat_path = path.parent / "heartbeat.json"
    supervisor_pid = os.getpid()
    receipt = {
        "format": "bodyrig-operator-launch",
        "version": 1,
        "launch_id": request["launch_id"],
        "category": request["category"],
        "pid": supervisor_pid,
        "process_role": "restart-safe-supervisor",
        "started_utc": request["started_utc"],
        "log_path": str(log_path),
        "request_path": str(path),
        "request_sha256": request["request_sha256"],
        "result_path": str(result_path),
        "context": request["context"],
    }
    _atomic_write_json(receipt_path, receipt)
    started_monotonic = time.monotonic()
    child_pid: int | None = None
    try:
        child = subprocess.Popen(
            [
                request["pwsh_path"],
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                request["command"],
            ],
            cwd=request["cwd"],
            stdin=subprocess.DEVNULL,
            shell=False,
        )
        child_pid = int(child.pid)
        while True:
            polled = child.poll()
            if polled is not None:
                exit_code = int(polled)
                break
            try:
                _write_heartbeat(
                    heartbeat_path,
                    launch_id=request["launch_id"],
                    supervisor_pid=supervisor_pid,
                    child_pid=child_pid,
                    request_sha256=request["request_sha256"],
                )
            except OSError as exc:
                print(
                    f"Operator launch heartbeat write failed; supervision continues: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(2.0)
    except OSError as exc:
        print(f"Could not start canonical operator child: {exc}", file=sys.stderr, flush=True)
        exit_code = 127

    finished_utc = _utc_now()
    duration = max(0.0, time.monotonic() - started_monotonic)
    result: dict[str, Any] = {
        "format": "bodyrig-operator-launch-result",
        "version": 1,
        "launch_id": request["launch_id"],
        "pid": supervisor_pid,
        "state": "succeeded" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "finished_utc": finished_utc,
        "duration_seconds": round(duration, 3),
        "request_sha256": request["request_sha256"],
    }
    if child_pid is not None:
        result["child_pid"] = child_pid
    _atomic_write_json(result_path, result)
    return 0


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 2:
        print("Usage: operator_launch_runner.py <request.json> <request-sha256>", file=sys.stderr)
        return 2
    try:
        return run_request(Path(values[0]).expanduser().resolve(), values[1])
    except OperatorLaunchRunnerError as exc:
        print(f"Operator launch supervisor rejected request: {exc}", file=sys.stderr, flush=True)
        return 2
    except (OSError, ValueError) as exc:
        print(f"Operator launch supervisor failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
