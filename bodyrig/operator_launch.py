from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .storage import data_dir


class OperatorLaunchError(RuntimeError):
    pass


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


def launch_canonical_operator(
    command: str,
    *,
    category: str,
    context: Mapping[str, Any],
    cwd: str | Path,
) -> dict[str, Any]:
    clean_command = str(command or "").strip()
    if not clean_command:
        raise OperatorLaunchError("Canonical operator command is empty")
    safe_category = str(category or "").strip()
    if not safe_category or any(
        ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for ch in safe_category.lower()
    ):
        raise OperatorLaunchError("Operator launch category is invalid")
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if not pwsh:
        raise OperatorLaunchError("PowerShell 7 (pwsh) was not found")

    runner = Path(__file__).with_name("operator_launch_runner.py").resolve()
    if not runner.is_file() or runner.is_symlink():
        raise OperatorLaunchError(f"Operator launch supervisor is unavailable: {runner}")

    workdir = Path(cwd).expanduser().resolve()
    if not workdir.is_dir():
        raise OperatorLaunchError(f"Operator launch working directory is unavailable: {workdir}")

    launch_id = f"{safe_category}-" + uuid.uuid4().hex
    root = data_dir() / "operator-launches" / safe_category / launch_id
    root.mkdir(parents=True, exist_ok=False)
    log_path = root / "operator.log"
    receipt_path = root / "launch.json"
    request_path = root / "request.json"
    result_path = root / "result.json"
    started_utc = _utc_now()

    request = {
        "format": "bodyrig-operator-launch-request",
        "version": 1,
        "launch_id": launch_id,
        "pwsh_path": str(Path(pwsh).expanduser().resolve()),
        "command": clean_command,
        "cwd": str(workdir),
        "started_utc": started_utc,
    }
    _atomic_write_json(request_path, request)
    try:
        request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise OperatorLaunchError(f"Could not hash canonical operator request: {exc}") from exc

    log = log_path.open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [sys.executable, str(runner), str(request_path), request_sha256],
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise OperatorLaunchError(f"Could not start canonical operator supervisor: {exc}") from exc
    finally:
        log.close()

    receipt = {
        "format": "bodyrig-operator-launch",
        "version": 1,
        "launch_id": launch_id,
        "category": safe_category,
        "pid": process.pid,
        "process_role": "restart-safe-supervisor",
        "started_utc": started_utc,
        "log_path": str(log_path),
        "request_path": str(request_path),
        "request_sha256": request_sha256,
        "result_path": str(result_path),
        "context": dict(context),
    }
    _atomic_write_json(receipt_path, receipt)
    return receipt
