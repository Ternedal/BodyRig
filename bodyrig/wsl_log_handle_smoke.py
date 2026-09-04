from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


SMOKE_CHILD_ENV = "BODYRIG_WSL_LOG_HANDLE_SMOKE_CHILD"
_SMOKE_MARKER = "bodyrig-wsl-log-smoke"


class WslLogHandleSmokeError(RuntimeError):
    pass


def _is_windows() -> bool:
    return os.name == "nt"


def _command_name(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].lower()


def _linux_python_from_command(command: Sequence[str]) -> str | None:
    argv = list(command)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        return None
    executable = argv[0]
    name = _command_name(executable)
    if name == "python" or name.startswith("python3"):
        return executable
    return None


def run_target_wsl_log_handle_smoke(
    *,
    wsl_exe: str,
    distribution: str,
    linux_command: Sequence[str],
    timeout_seconds: int = 20,
) -> float | None:
    """Prove adapter.log cleanup on the actual Windows/WSL boundary.

    The smoke launches a nested BodyRig WSL bridge whose stdout/stderr are
    redirected to a temporary adapter.log exactly like the expensive adapter
    boundaries. The Linux interpreter emits one marker and exits normally. The
    nested bridge must return successfully, BodyRig must be able to read the
    marker, and Windows must allow adapter.log to be unlinked immediately.

    Descendant-handle inheritance is intentionally covered by the dedicated
    Windows regression test instead of being asserted here. A detached Linux
    descendant is not guaranteed to keep writing through the original wsl.exe
    client after its direct Linux parent exits, so requiring descendant output
    would test undocumented WSL client behavior rather than BodyRig cleanup.

    No source media, GPU work, credentials or persistent evidence are touched.
    Non-Python Linux commands are left alone because there is no authoritative
    interpreter available to construct the probe. Canonical BodyRig observation,
    identity and high-fidelity WSL adapters are Python-based.
    """

    if not _is_windows():
        return None
    if not isinstance(wsl_exe, str) or not wsl_exe.strip():
        raise WslLogHandleSmokeError("WSL executable is required for target log-handle smoke")
    if not isinstance(distribution, str) or not distribution.strip():
        raise WslLogHandleSmokeError("WSL distribution is required for target log-handle smoke")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 5 <= timeout_seconds <= 60:
        raise WslLogHandleSmokeError("target log-handle smoke timeout must be in 5..60 seconds")

    linux_python = _linux_python_from_command(linux_command)
    if linux_python is None:
        return None

    probe_code = f"print({_SMOKE_MARKER!r}, flush=True)"
    env = os.environ.copy()
    env[SMOKE_CHILD_ENV] = "1"
    nested_bridge = [
        sys.executable,
        "-m",
        "bodyrig.wsl_adapter_bridge",
        "--distribution",
        distribution.strip(),
        "--wsl-exe",
        wsl_exe,
        "--",
        linux_python,
        "-c",
        probe_code,
    ]

    try:
        with tempfile.TemporaryDirectory(prefix="bodyrig-target-wsl-log-smoke-") as temp_name:
            log_path = Path(temp_name) / "adapter.log"
            started = time.monotonic()
            with log_path.open("wb") as log:
                completed = subprocess.run(
                    nested_bridge,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    check=False,
                    close_fds=True,
                    env=env,
                    timeout=timeout_seconds,
                )
            elapsed = time.monotonic() - started

            try:
                log_text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise WslLogHandleSmokeError("target WSL smoke could not read adapter.log after bridge completion") from exc

            if completed.returncode != 0:
                detail = log_text.strip()[-2000:]
                raise WslLogHandleSmokeError(
                    f"target WSL bridge smoke failed with exit code {completed.returncode}: {detail}"
                )
            if _SMOKE_MARKER not in log_text:
                raise WslLogHandleSmokeError("target WSL bridge smoke did not receive probe output")

            try:
                log_path.unlink()
            except PermissionError as exc:
                raise WslLogHandleSmokeError(
                    f"adapter.log remained locked after target WSL bridge completion: {exc}"
                ) from exc
            return elapsed
    except subprocess.TimeoutExpired as exc:
        raise WslLogHandleSmokeError("target WSL log-handle smoke timed out") from exc
    except OSError as exc:
        raise WslLogHandleSmokeError(f"target WSL log-handle smoke could not complete: {exc}") from exc
