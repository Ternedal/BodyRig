from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .storage import data_dir


class OperatorLaunchError(RuntimeError):
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
        "started_utc": datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "log_path": str(log_path),
        "context": dict(context),
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt
