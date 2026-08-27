from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


SMOKE_CHILD_ENV = "BODYRIG_WSL_LOG_HANDLE_SMOKE_CHILD"
_PARENT_MARKER = "bodyrig-wsl-log-smoke-parent"
_DESCENDANT_MARKER = "bodyrig-wsl-log-smoke-descendant"
_DESCENDANT_SLEEP_SECONDS = 1.25
_MINIMUM_DRAIN_SECONDS = 1.0


class WslLogHandleSmokeError(RuntimeError):
    pass


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
    """Reproduce the adapter.log lifecycle on the actual Windows/WSL boundary.

    The smoke launches a nested BodyRig WSL bridge whose stdout/stderr are
    redirected to a temporary adapter.log exactly like the expensive adapter
    boundaries. The Linux parent deliberately exits while a descendant keeps
    stdout open. The nested bridge must drain the descendant pipe before it
    returns, after which Windows must allow adapter.log to be unlinked
    immediately. No source media, GPU work, credentials or persistent evidence
    are touched.

    Non-Python Linux commands are left alone because there is no authoritative
    interpreter available to construct the parent/descendant probe. Canonical
    BodyRig observation, identity and high-fidelity WSL adapters are Python-based.
    """

    if os.name != "nt":
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

    descendant_code = (
        "import time; "
        f"print({_DESCENDANT_MARKER!r}, flush=True); "
        f"time.sleep({_DESCENDANT_SLEEP_SECONDS!r})"
    )
    parent_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
        "stdout=sys.stdout, stderr=sys.stderr, close_fds=False); "
        f"print({_PARENT_MARKER!r}, flush=True)"
    )

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
        parent_code,
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
            if _PARENT_MARKER not in log_text or _DESCENDANT_MARKER not in log_text:
                raise WslLogHandleSmokeError("target WSL bridge smoke did not receive both parent and descendant output")
            if elapsed < _MINIMUM_DRAIN_SECONDS:
                raise WslLogHandleSmokeError(
                    "target WSL bridge returned before the descendant pipe writer closed"
                )

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
