from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
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


def _record_process_completion(
    process: subprocess.Popen[bytes],
    *,
    launch_id: str,
    result_path: Path,
    started_monotonic: float,
) -> None:
    try:
        exit_code = int(process.wait())
        finished_utc = _utc_now()
        duration = max(0.0, time.monotonic() - started_monotonic)
        _atomic_write_json(
            result_path,
            {
                "format": "bodyrig-operator-launch-result",
                "version": 1,
                "launch_id": launch_id,
                "pid": int(process.pid),
                "state": "succeeded" if exit_code == 0 else "failed",
                "exit_code": exit_code,
                "finished_utc": finished_utc,
                "duration_seconds": round(duration, 3),
            },
        )
    except (OSError, ValueError):
        # The launch itself is already in progress. If BodyRig cannot persist the
        # terminal receipt, the read side deliberately reports the launch as
        # terminal/unknown rather than inventing PASS/FAIL.
        return


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
    if not safe_category or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in safe_category.lower()):
        raise OperatorLaunchError("Operator launch category is invalid")
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if not pwsh:
        raise OperatorLaunchError("PowerShell 7 (pwsh) was not found")

    launch_id = f"{safe_category}-" + uuid.uuid4().hex
    root = data_dir() / "operator-launches" / safe_category / launch_id
    root.mkdir(parents=True, exist_ok=False)
    log_path = root / "operator.log"
    receipt_path = root / "launch.json"
    result_path = root / "result.json"
    started_utc = _utc_now()
    started_monotonic = time.monotonic()
    log = log_path.open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", clean_command],
            cwd=str(Path(cwd).expanduser().resolve()),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise OperatorLaunchError(f"Could not start canonical operator: {exc}") from exc
    finally:
        log.close()

    receipt = {
        "format": "bodyrig-operator-launch",
        "version": 1,
        "launch_id": launch_id,
        "category": safe_category,
        "pid": process.pid,
        "started_utc": started_utc,
        "log_path": str(log_path),
        "result_path": str(result_path),
        "context": dict(context),
    }
    _atomic_write_json(receipt_path, receipt)

    watcher = threading.Thread(
        target=_record_process_completion,
        kwargs={
            "process": process,
            "launch_id": launch_id,
            "result_path": result_path,
            "started_monotonic": started_monotonic,
        },
        name=f"bodyrig-operator-watch-{process.pid}",
        daemon=True,
    )
    try:
        watcher.start()
    except RuntimeError:
        # The operator process is already running, so do not lie by failing the
        # launch request. Drift will show terminal/unknown if no result arrives.
        pass
    return receipt
