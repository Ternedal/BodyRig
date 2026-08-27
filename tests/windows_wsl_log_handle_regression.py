from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("windows_wsl_log_handle_regression.py must run on Windows")

    descendant_code = (
        "import sys,time; "
        "print('descendant inherited stdout', flush=True); "
        "time.sleep(1.25)"
    )
    parent_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
        "stdout=sys.stdout, stderr=sys.stderr, close_fds=False); "
        "print('immediate parent exiting', flush=True)"
    )
    bridge_code = (
        "import sys; "
        "from bodyrig.wsl_adapter_bridge import _run_wsl_forward; "
        "completed = _run_wsl_forward(sys.argv[1:]); "
        "raise SystemExit(completed.returncode)"
    )

    with tempfile.TemporaryDirectory(prefix="bodyrig-win32-log-lock-") as temp_name:
        log_path = Path(temp_name) / "adapter.log"
        started = time.monotonic()
        with log_path.open("wb") as log:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    bridge_code,
                    sys.executable,
                    "-c",
                    parent_code,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                check=False,
            )
        elapsed = time.monotonic() - started

        if completed.returncode != 0:
            raise SystemExit(f"bridge simulation failed with exit code {completed.returncode}")
        if elapsed < 1.0:
            raise SystemExit(
                "bridge returned before inherited pipe writer closed; descendant lifecycle was not drained"
            )

        try:
            log_path.unlink()
        except PermissionError as exc:
            raise SystemExit(
                f"adapter.log remained locked after bridge completion: {exc}"
            ) from exc

    print("Windows WSL log-handle regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
