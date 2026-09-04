from __future__ import annotations

import subprocess
import tempfile
from typing import Sequence


def run_wsl_file_capture(
    command: Sequence[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run a Windows->WSL command without Python-managed stdout/stderr pipes.

    WSL descendants can inherit stdio handles beyond the lifetime of wsl.exe.
    Python PIPE capture can therefore wait for EOF after the wsl.exe process
    itself has already exited. Seekable temporary files keep completion tied to
    the process handle while preserving bounded UTF-8 diagnostic output.
    """

    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError("WSL command must contain non-empty argv entries")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise ValueError("WSL command timeout must be a positive integer")

    with (
        tempfile.TemporaryFile(mode="w+b") as stdout_file,
        tempfile.TemporaryFile(mode="w+b") as stderr_file,
    ):
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            check=False,
            timeout=timeout,
        )
        stdout_file.flush()
        stderr_file.flush()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(argv, completed.returncode, stdout, stderr)
