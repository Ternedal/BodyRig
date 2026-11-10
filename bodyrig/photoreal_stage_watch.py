"""Progress, ETA and a no-output stop for long ExAvatar stages.

ExAvatar preprocessing and teacher training run for hours. Before this module
they ran without any bound, so a hung stage could hold a run for days, and the
only sign of how long a healthy run would take was the upstream log line.

``run_watched_process`` runs one stage with its output in its own log, as
before, and additionally:

- parses the upstream progress lines (teacher ``Epoch e/E itr i/I: speed: s``,
  SMPL-X fit ``epoch e/E itr_data d/D itr_opt o/O:``);
- writes ``<log stem>.progress.json`` atomically while the stage runs, with
  completed/total, the measured seconds per unit over the last minutes, and
  an ETA;
- stops the stage's whole process group when it has written no output for
  ``stall_seconds``, and reports it as stalled;
- appends one line per stage to ``stage-timing.jsonl``.

None of this changes what a stage computes. The progress and timing files are
evidence for the operator, never an acceptance authority.

The functions between the two ``shared source`` markers are copied byte for
byte into ``tools/photoreal_exavatar_teacher_adapter.py``, which must stay a
single hash-bound file. ``tests/test_photoreal_stage_watch.py`` fails if the
copies differ.
"""

from __future__ import annotations

import collections
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
EXAVATAR_TRAIN_LINE = re.compile(
    r"Epoch (\d+)/(\d+) itr (\d+)/(\d+):.*?speed: ([0-9]+(?:\.[0-9]+)?)\("
)
EXAVATAR_FIT_LINE = re.compile(
    r"epoch (\d+)/(\d+) itr_data (\d+)/(\d+) itr_opt (\d+)/(\d+):"
)
# Pinned upstream fitting/main/config.py, set_itr_opt_num: 500 optimisation
# steps per batch in epoch 0 and 250 in every later epoch.
EXAVATAR_FIT_STEPS = (500, 250)
STAGE_PROGRESS_FORMAT = "bodyrig-exavatar-stage-progress"
STAGE_TIMING_FORMAT = "bodyrig-exavatar-stage-timing"
STAGE_WATCH_VERSION = 1
# The control-plane UI flags a stage as "stalled-suspected" after 30 minutes
# without log output. The enforced stop waits twice as long.
DEFAULT_STALL_SECONDS = 3600.0
RATE_WINDOW_SECONDS = 900.0
RATE_MIN_SPAN_SECONDS = 60.0

# --- shared source: begin -------------------------------------------------


class StageStalled(RuntimeError):
    pass


def parse_exavatar_train_line(line: str) -> dict[str, Any] | None:
    match = EXAVATAR_TRAIN_LINE.search(line)
    if match is None:
        return None
    epoch, end_epoch, itr, per_epoch = (int(match.group(index)) for index in range(1, 5))
    if end_epoch < 1 or per_epoch < 1 or not 0 <= epoch < end_epoch or not 0 <= itr < per_epoch:
        return None
    return {
        "unit": "iteration",
        "completed": epoch * per_epoch + itr + 1,
        "total": end_epoch * per_epoch,
        "epoch": epoch,
        "end_epoch": end_epoch,
        "upstream_seconds_per_unit": float(match.group(5)),
    }


def parse_exavatar_fit_line(line: str) -> dict[str, Any] | None:
    match = EXAVATAR_FIT_LINE.search(line)
    if match is None:
        return None
    epoch, end_epoch, batch, batches, step, steps = (int(match.group(index)) for index in range(1, 7))
    if (
        end_epoch < 1
        or batches < 1
        or steps < 1
        or not 0 <= epoch < end_epoch
        or not 0 <= batch < batches
        or not 0 <= step < steps
    ):
        return None
    schedule = [EXAVATAR_FIT_STEPS[0] if index == 0 else EXAVATAR_FIT_STEPS[1] for index in range(end_epoch)]
    # A schedule other than the pinned one gives no honest total: report the
    # position, but no percentage or ETA.
    known = steps == schedule[epoch]
    return {
        "unit": "fit-step",
        "completed": sum(schedule[:epoch]) * batches + batch * steps + step + 1 if known else None,
        "total": sum(schedule) * batches if known else None,
        "epoch": epoch,
        "end_epoch": end_epoch,
        "upstream_seconds_per_unit": None,
    }


def _utc(stamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


class StageProgress:
    def __init__(
        self,
        *,
        stage: str,
        parser: Callable[[str], dict[str, Any] | None] | None,
        stall_seconds: float,
        started: float,
        started_wall: float,
    ) -> None:
        self.stage = stage
        self.parser = parser
        self.stall_seconds = float(stall_seconds)
        self.started = started
        self.started_wall = started_wall
        self.last_output = started
        self.pending = b""
        self.latest: dict[str, Any] | None = None
        self.window: collections.deque[tuple[float, int]] = collections.deque(maxlen=1024)
        self.state = "running"
        self.exit_code: int | None = None
        self.pid: int | None = None

    def feed(self, chunk: bytes, now: float) -> None:
        if not chunk:
            return
        self.last_output = now
        if self.parser is None:
            return
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()[-65536:]
        newest: int | None = None
        for raw in lines:
            for part in raw.split(b"\r"):
                parsed = self.parser(ANSI_ESCAPE.sub("", part.decode("utf-8", errors="replace")))
                if parsed is None:
                    continue
                completed = parsed.get("completed")
                previous = self.latest.get("completed") if self.latest is not None else None
                if completed is not None and previous is not None and completed < previous:
                    self.window.clear()
                    newest = None
                self.latest = parsed
                if completed is not None:
                    newest = completed
        if newest is not None:
            self.window.append((now, newest))
            while len(self.window) > 2 and now - self.window[0][0] > RATE_WINDOW_SECONDS:
                self.window.popleft()

    def seconds_per_unit(self) -> float | None:
        if len(self.window) < 2:
            return None
        (first_time, first_done), (last_time, last_done) = self.window[0], self.window[-1]
        if last_time - first_time < RATE_MIN_SPAN_SECONDS or last_done <= first_done:
            return None
        return (last_time - first_time) / (last_done - first_done)

    def snapshot(self, now: float, wall_now: float) -> dict[str, Any]:
        latest = self.latest or {}
        completed = latest.get("completed")
        total = latest.get("total")
        rate = self.seconds_per_unit()
        eta: float | None = None
        if self.state == "finished":
            eta = 0.0
        elif self.state == "running" and rate is not None and completed is not None and total is not None:
            eta = max(0, total - completed) * rate
        silent = max(0.0, now - self.last_output)
        return {
            "format": STAGE_PROGRESS_FORMAT,
            "version": STAGE_WATCH_VERSION,
            "stage": self.stage,
            "state": self.state,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "started_utc": _utc(self.started_wall),
            "updated_utc": _utc(wall_now),
            "elapsed_seconds": round(max(0.0, now - self.started), 3),
            "last_output_utc": _utc(wall_now - silent),
            "seconds_since_output": round(silent, 3),
            "stall_after_seconds": self.stall_seconds,
            "unit": latest.get("unit"),
            "completed": completed,
            "total": total,
            "percent": round(100.0 * completed / total, 2) if completed is not None and total else None,
            "epoch": latest.get("epoch"),
            "end_epoch": latest.get("end_epoch"),
            "seconds_per_unit": round(rate, 4) if rate is not None else None,
            "upstream_seconds_per_unit": latest.get("upstream_seconds_per_unit"),
            "eta_seconds": round(eta, 1) if eta is not None else None,
            "eta_utc": _utc(wall_now + eta) if eta is not None else None,
            "authority": False,
        }


def write_stage_progress(path: Path, value: Mapping[str, Any]) -> bool:
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    except (OSError, ValueError):
        return False
    return True


def append_stage_timing(path: Path, progress: StageProgress, *, log_name: str, now: float, wall_now: float) -> bool:
    latest = progress.latest or {}
    rate = progress.seconds_per_unit()
    record = {
        "format": STAGE_TIMING_FORMAT,
        "version": STAGE_WATCH_VERSION,
        "stage": progress.stage,
        "state": progress.state,
        "exit_code": progress.exit_code,
        "log": log_name,
        "started_utc": _utc(progress.started_wall),
        "finished_utc": _utc(wall_now),
        "elapsed_seconds": round(max(0.0, now - progress.started), 3),
        "unit": latest.get("unit"),
        "completed": latest.get("completed"),
        "total": latest.get("total"),
        "seconds_per_unit": round(rate, 4) if rate is not None else None,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
    except (OSError, ValueError):
        return False
    return True


def stop_process_group(process: subprocess.Popen[bytes], *, grace_seconds: float = 30.0) -> None:
    # The stage runs in its own session, so the group holds the stage and
    # every descendant (DataLoader workers, COLMAP binaries) and nothing else.
    killpg = getattr(os, "killpg", None)
    for name, wait_seconds in (("SIGTERM", grace_seconds), ("SIGKILL", 10.0)):
        try:
            if killpg is not None:
                killpg(process.pid, getattr(signal, name))
            elif name == "SIGKILL":
                process.kill()
            else:
                process.terminate()
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            continue


def run_watched_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log_path: Path,
    stage: str,
    parser: Callable[[str], dict[str, Any] | None] | None,
    stall_seconds: float,
    poll_seconds: float = 5.0,
    write_seconds: float = 15.0,
    report: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    progress_path = log_path.with_name(log_path.stem + ".progress.json")
    timing_path = log_path.with_name("stage-timing.jsonl")
    progress = StageProgress(
        stage=stage,
        parser=parser,
        stall_seconds=stall_seconds,
        started=time.monotonic(),
        started_wall=time.time(),
    )

    def finish(state: str, code: int | None) -> None:
        progress.state = state
        progress.exit_code = code
        now, wall_now = time.monotonic(), time.time()
        write_stage_progress(progress_path, progress.snapshot(now, wall_now))
        append_stage_timing(timing_path, progress, log_name=log_path.name, now=now, wall_now=wall_now)

    def interrupted(signum: int, frame: Any) -> None:
        raise SystemExit(128 + signum)

    # The stage gets its own session, so a signal to this process no longer
    # reaches it directly. Turn SIGTERM/SIGHUP into an exception, which stops
    # the stage's group below, as Ctrl+C (KeyboardInterrupt) already does.
    previous_handlers: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous_handlers[sig] = signal.signal(sig, interrupted)
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
            )
            progress.pid = process.pid
            try:
                with log_path.open("rb") as reader:
                    last_write: float | None = None
                    while True:
                        try:
                            code: int | None = process.wait(timeout=poll_seconds)
                        except subprocess.TimeoutExpired:
                            code = None
                        now = time.monotonic()
                        progress.feed(reader.read(), now)
                        if code is not None:
                            break
                        if now - progress.last_output > progress.stall_seconds:
                            stop_process_group(process)
                            progress.feed(reader.read(), time.monotonic())
                            finish("stalled", process.returncode)
                            raise StageStalled(
                                f"made no output for {int(progress.stall_seconds)} s and was stopped"
                            )
                        if last_write is None or now - last_write >= write_seconds:
                            snapshot = progress.snapshot(now, time.time())
                            write_stage_progress(progress_path, snapshot)
                            if report is not None:
                                try:
                                    report(snapshot)
                                except Exception:
                                    pass
                            last_write = now
            except StageStalled:
                raise
            except BaseException:
                if process.poll() is None:
                    stop_process_group(process)
                finish("stopped", process.returncode)
                raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    finish("finished" if code == 0 else "failed", code)
    return int(code)


# --- shared source: end ---------------------------------------------------

SHARED_NAMES = (
    "StageStalled",
    "parse_exavatar_train_line",
    "parse_exavatar_fit_line",
    "_utc",
    "StageProgress",
    "write_stage_progress",
    "append_stage_timing",
    "stop_process_group",
    "run_watched_process",
)
SHARED_CONSTANTS = (
    "ANSI_ESCAPE",
    "EXAVATAR_TRAIN_LINE",
    "EXAVATAR_FIT_LINE",
    "EXAVATAR_FIT_STEPS",
    "STAGE_PROGRESS_FORMAT",
    "STAGE_TIMING_FORMAT",
    "STAGE_WATCH_VERSION",
    "RATE_WINDOW_SECONDS",
    "RATE_MIN_SPAN_SECONDS",
)
