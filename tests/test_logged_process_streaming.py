from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from bodyrig.logged_process import run_logged_process


def test_short_output_reaches_the_log_while_the_child_runs(tmp_path: Path) -> None:
    # The child prints one short line, then waits until that line is in the
    # log. A drain that waits for a full 64 KiB block never writes it, so the
    # child gives up after 10 s and says so.
    marker = tmp_path / "seen"
    log_path = tmp_path / "adapter.log"
    code = (
        "import time, pathlib\n"
        "print('progress 1%', flush=True)\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "deadline = time.monotonic() + 10\n"
        "while not marker.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.02)\n"
        "print('released' if marker.exists() else 'buffered until exit', flush=True)\n"
    )
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            try:
                if b"progress 1%" in log_path.read_bytes():
                    marker.touch()
                    return
            except OSError:
                pass
            time.sleep(0.02)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        completed = run_logged_process([sys.executable, "-c", code], log_path=log_path, timeout_seconds=60)
    finally:
        stop.set()
        watcher.join(2)
    assert completed.returncode == 0
    assert b"released" in log_path.read_bytes()
