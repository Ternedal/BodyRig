from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence


class LoggedProcessError(OSError):
    pass


def run_logged_process(
    command: Sequence[str],
    *,
    log_path: str | Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run a child without ever giving it ownership of the log file handle.

    stdout/stderr are merged into a pipe owned by BodyRig and drained on a
    dedicated thread into ``log_path``. Descendants may inherit the pipe, but
    they cannot inherit the Windows handle for the cleanup-bound adapter.log.
    The drain is also bounded by the same overall timeout, so a descendant that
    keeps the pipe open forever cannot stall cleanup indefinitely.
    """

    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise LoggedProcessError("logged process command must contain non-empty argv entries")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise LoggedProcessError("logged process timeout must be a positive integer")

    path = Path(log_path)
    pump_errors: list[BaseException] = []
    timed_out = False

    with path.open("wb") as log:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            close_fds=True,
        )
        if process.stdout is None:  # pragma: no cover - PIPE above guarantees this
            process.kill()
            process.wait()
            raise LoggedProcessError("logged process did not create an output pipe")

        def pump() -> None:
            try:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    log.write(chunk)
                    log.flush()
            except (OSError, ValueError) as exc:
                if not timed_out:
                    pump_errors.append(exc)

        drain = threading.Thread(target=pump, name="bodyrig-log-drain", daemon=True)
        drain.start()
        deadline = time.monotonic() + timeout_seconds

        try:
            process.wait(timeout=timeout_seconds)
            remaining = max(0.0, deadline - time.monotonic())
            drain.join(remaining)
            if drain.is_alive():
                timed_out = True
                process.stdout.close()
                drain.join(1.0)
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            if not process.stdout.closed:
                process.stdout.close()
            drain.join(1.0)
            raise
        finally:
            if not process.stdout.closed:
                process.stdout.close()

        if pump_errors:
            raise LoggedProcessError(f"could not drain logged process output: {pump_errors[0]}")
        return subprocess.CompletedProcess(argv, int(process.returncode or 0))
