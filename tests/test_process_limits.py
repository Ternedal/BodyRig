"""bodyrig.process_limits on the real OS: tree kill on timeout, memory bound, normal exit."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from bodyrig.process_limits import Limits, run_bounded, tail

GRANDCHILD = r"""
import subprocess, sys, time
beat = sys.argv[1]
code = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.05)\n"
subprocess.Popen([sys.executable, "-c", code, beat])
time.sleep(600)
"""


def _run(tmp_path: Path, code: str, *args: str, **limits) -> object:
    script = tmp_path / "child.py"
    script.write_text(code, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    return run_bounded([sys.executable, str(script), *args], cwd=tmp_path, env=env, limits=Limits(**limits),
                       stdout_path=tmp_path / "out.txt", stderr_path=tmp_path / "err.txt")


def test_normal_exit_reports_code_and_applied_limits(tmp_path: Path) -> None:
    result = _run(tmp_path, "import sys; print('hello'); sys.exit(4)", wall_seconds=30)
    assert result.returncode == 4 and not result.timed_out and not result.memory_exceeded
    assert "hello" in tail(tmp_path / "out.txt")
    if os.name == "nt":
        assert result.applied["job_object"] and result.applied["kill_on_close"] and result.applied["ui_restricted"]
    else:
        assert result.applied["process_group_kill"]


def test_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    beat = tmp_path / "beat.txt"
    started = time.perf_counter()
    result = _run(tmp_path, GRANDCHILD, str(beat), wall_seconds=2)
    assert result.timed_out and time.perf_counter() - started < 15
    deadline = time.time() + 10
    while not beat.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert beat.exists(), "grandchild never started"
    time.sleep(0.5)
    size = beat.stat().st_size
    time.sleep(1.0)
    assert beat.stat().st_size == size, "grandchild survived the timeout"


def test_memory_limit_stops_the_child(tmp_path: Path) -> None:
    code = "import time\nblock = b'x' * (600 * 1024 * 1024)\ntime.sleep(20)\n"
    result = _run(tmp_path, code, wall_seconds=60, memory_bytes=200 * 1024 * 1024)
    assert result.returncode != 0 and not result.timed_out
    if sys.platform.startswith("linux"):
        assert result.memory_exceeded and result.peak_memory_bytes > 200 * 1024 * 1024


ESCAPING_GRANDCHILD = r"""
import subprocess, sys, time
beat, mode = sys.argv[1], sys.argv[2]
if mode == "memory":
    code = "import sys, time\nblock = b'x' * (600 * 1024 * 1024)\nopen(sys.argv[1], 'w').write('allocated')\ntime.sleep(60)\n"
else:
    code = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.05)\n"
subprocess.Popen([sys.executable, "-c", code, beat], start_new_session=True)
time.sleep(600)
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc-based tree tracking")
def test_descendant_in_its_own_session_is_still_killed(tmp_path: Path) -> None:
    beat = tmp_path / "beat.txt"
    result = _run(tmp_path, ESCAPING_GRANDCHILD, str(beat), "beat", wall_seconds=2)
    assert result.timed_out and beat.exists()
    time.sleep(0.5)
    size = beat.stat().st_size
    time.sleep(1.0)
    assert beat.stat().st_size == size, "setsid grandchild survived the timeout"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc-based tree tracking")
def test_memory_of_a_descendant_in_its_own_session_counts(tmp_path: Path) -> None:
    marker = tmp_path / "allocated.txt"
    result = _run(tmp_path, ESCAPING_GRANDCHILD, str(marker), "memory", wall_seconds=60,
                  memory_bytes=200 * 1024 * 1024)
    assert result.memory_exceeded and not result.timed_out
