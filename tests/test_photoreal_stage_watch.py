from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preprocess as preprocess
from bodyrig import photoreal_stage_watch as watch

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"
MODULE_PATH = ROOT / "bodyrig" / "photoreal_stage_watch.py"
BEGIN = "# --- shared source: begin"
END = "# --- shared source: end"

posix_only = pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX; the stages run in WSL")

# One real upstream line, as the pinned ExAvatar colorlogger writes it.
TRAIN_LINE = (
    "\x1b[92m11-10 01:02:03\x1b[0m Epoch 1/5 itr 9/1800: speed: 2.35(2.10s r0.05)s/itr "
    "1.18h/epoch loss_rgb: 0.0123 loss_ssim: 0.0456"
)
FIT_LINE = "['epoch 1/3 itr_data 1/2 itr_opt 9/250:', 'lr: 0.01', 'loss_kpt: 0.1234']"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("bodyrig_test_stage_watch_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shared_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(BEGIN)
    end = text.index("\n", text.index(END)) + 1
    return text[start:end]


def _child(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


def _read_progress(log_path: Path) -> dict:
    return json.loads(log_path.with_name(log_path.stem + ".progress.json").read_text(encoding="utf-8"))


def _read_timing(log_path: Path) -> list[dict]:
    lines = log_path.with_name("stage-timing.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        status = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return status[status.rfind(")") + 2] != "Z"


# --- the adapter's copy ---------------------------------------------------


def test_adapter_carries_a_byte_identical_copy_of_the_shared_source() -> None:
    assert _shared_block(ADAPTER_PATH) == _shared_block(MODULE_PATH)


def test_adapter_constants_match_the_module() -> None:
    adapter = _load_adapter()
    for name in watch.SHARED_CONSTANTS:
        ours, theirs = getattr(watch, name), getattr(adapter, name)
        if hasattr(ours, "pattern"):
            assert theirs.pattern == ours.pattern, name
        else:
            assert theirs == ours, name
    for name in watch.SHARED_NAMES:
        assert callable(getattr(adapter, name)), name


def test_adapter_stays_free_of_bodyrig_imports() -> None:
    # The teacher transport revision hashes this one file; an import from the
    # bodyrig package would run code that the revision does not cover.
    text = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "import bodyrig" not in text and "from bodyrig" not in text


# --- parsers ----------------------------------------------------------------


def test_train_line_is_parsed_through_the_colour_codes() -> None:
    parsed = watch.parse_exavatar_train_line(watch.ANSI_ESCAPE.sub("", TRAIN_LINE))
    assert parsed == {
        "unit": "iteration",
        "completed": 1 * 1800 + 9 + 1,
        "total": 5 * 1800,
        "epoch": 1,
        "end_epoch": 5,
        "upstream_seconds_per_unit": 2.35,
    }


@pytest.mark.parametrize(
    "line",
    [
        "Epoch 5/5 itr 0/10: speed: 1.0(1.0s r0.0)s/itr",
        "Epoch 0/5 itr 10/10: speed: 1.0(1.0s r0.0)s/itr",
        "Epoch 0/5 itr 0/0: speed: 1.0(1.0s r0.0)s/itr",
        "Epoch 0/5 itr 0/10:",
        "Load checkpoint from /x/snapshot_3.pth",
    ],
)
def test_train_parser_rejects_impossible_or_other_lines(line: str) -> None:
    assert watch.parse_exavatar_train_line(line) is None


def test_fit_line_on_the_pinned_schedule_gives_a_total() -> None:
    parsed = watch.parse_exavatar_fit_line(FIT_LINE)
    assert parsed is not None
    # epoch 0: 2 batches x 500 steps; then batch 1 of epoch 1 at step 9.
    assert parsed["completed"] == 2 * 500 + 1 * 250 + 9 + 1
    assert parsed["total"] == 2 * (500 + 250 + 250)
    assert parsed["unit"] == "fit-step"


def test_fit_line_off_the_pinned_schedule_gives_no_total() -> None:
    parsed = watch.parse_exavatar_fit_line("epoch 1/3 itr_data 0/2 itr_opt 9/300:")
    assert parsed is not None
    assert parsed["completed"] is None and parsed["total"] is None
    assert watch.parse_exavatar_fit_line("epoch 3/3 itr_data 0/2 itr_opt 9/250:") is None


# --- rate and ETA -------------------------------------------------------------


def _line(epoch: int, itr: int, per_epoch: int = 100) -> bytes:
    return f"Epoch {epoch}/5 itr {itr}/{per_epoch}: speed: 9.99(1.0s r0.0)s/itr\n".encode()


def test_rate_and_eta_come_from_measured_progress_not_the_upstream_average() -> None:
    progress = watch.StageProgress(
        stage="t", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=1_000_000.0
    )
    progress.feed(_line(0, 0), 10.0)
    progress.feed(_line(0, 30), 40.0)
    assert progress.seconds_per_unit() is None  # under a minute of evidence
    assert progress.snapshot(40.0, 1_000_040.0)["eta_seconds"] is None
    progress.feed(_line(0, 60), 70.0)
    assert progress.seconds_per_unit() == pytest.approx(1.0)
    snapshot = progress.snapshot(70.0, 1_000_070.0)
    assert snapshot["completed"] == 61 and snapshot["total"] == 500
    assert snapshot["percent"] == 12.2
    assert snapshot["eta_seconds"] == pytest.approx(439.0)
    assert snapshot["eta_utc"] == "1970-01-12T13:55:09Z"  # 1_000_070 + 439 s
    assert snapshot["upstream_seconds_per_unit"] == 9.99
    assert snapshot["authority"] is False


def test_rate_follows_the_recent_window_only() -> None:
    progress = watch.StageProgress(
        stage="t", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=0.0
    )
    progress.feed(_line(0, 0), 0.0)
    progress.feed(_line(0, 9), 1000.0)  # 100 s per iteration, long ago
    for step in range(1, 11):
        progress.feed(_line(0, 9 + step * 10), 1000.0 + step * 100.0)  # then 10 s per iteration
    assert progress.seconds_per_unit() == pytest.approx(10.0)


def test_a_restart_from_an_earlier_position_resets_the_rate() -> None:
    progress = watch.StageProgress(
        stage="t", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=0.0
    )
    progress.feed(_line(2, 0), 0.0)
    progress.feed(_line(2, 50), 100.0)
    progress.feed(_line(1, 0), 200.0)
    assert progress.seconds_per_unit() is None
    assert progress.latest is not None and progress.latest["epoch"] == 1
    progress.feed(_line(1, 60), 260.0)
    assert progress.seconds_per_unit() == pytest.approx(1.0)  # only the run after the restart


def test_partial_lines_and_carriage_returns_are_handled() -> None:
    progress = watch.StageProgress(
        stage="t", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=0.0
    )
    whole = _line(0, 4)
    progress.feed(whole[:20], 1.0)
    assert progress.latest is None
    progress.feed(whole[20:] + b"tqdm 1/9\rEpoch 0/5 itr 5/100: speed: 1.0(1.0s r0.0)s/itr\n", 2.0)
    assert progress.latest is not None and progress.latest["completed"] == 6


# --- real child processes -------------------------------------------------------


@posix_only
def test_a_finished_stage_writes_progress_and_timing(tmp_path: Path) -> None:
    argv = _child(
        tmp_path,
        """
        import sys, time
        for itr in range(4):
            sys.stderr.write("\\x1b[92m11-10\\x1b[0m Epoch 0/1 itr %d/4: speed: 0.01(0.01s r0.00)s/itr\\n" % itr)
            sys.stderr.flush()
            time.sleep(0.05)
        """,
    )
    log_path = tmp_path / "logs" / "train.log"
    log_path.parent.mkdir()
    seen: list[dict] = []
    code = watch.run_watched_process(
        argv,
        cwd=tmp_path,
        env=dict(os.environ),
        log_path=log_path,
        stage="teacher-train",
        parser=watch.parse_exavatar_train_line,
        stall_seconds=30,
        poll_seconds=0.02,
        write_seconds=0.0,
        report=seen.append,
    )
    assert code == 0
    assert b"Epoch 0/1 itr 3/4" in log_path.read_bytes()
    progress = _read_progress(log_path)
    assert progress["state"] == "finished" and progress["exit_code"] == 0
    assert progress["completed"] == 4 and progress["total"] == 4 and progress["percent"] == 100.0
    assert progress["eta_seconds"] == 0.0
    (timing,) = _read_timing(log_path)
    assert timing["stage"] == "teacher-train" and timing["state"] == "finished"
    assert timing["log"] == "train.log" and timing["completed"] == 4
    assert seen and all(item["state"] == "running" for item in seen)
    assert not list(log_path.parent.glob("*.tmp"))


@posix_only
def test_a_failing_stage_returns_its_code_and_records_it(tmp_path: Path) -> None:
    argv = _child(tmp_path, "import sys; print('boom'); sys.exit(7)")
    log_path = tmp_path / "fit.log"
    code = watch.run_watched_process(
        argv, cwd=tmp_path, env=dict(os.environ), log_path=log_path, stage="05-smplx-fit",
        parser=watch.parse_exavatar_fit_line, stall_seconds=30, poll_seconds=0.02,
    )
    assert code == 7
    assert _read_progress(log_path)["state"] == "failed"
    assert _read_timing(log_path)[-1]["exit_code"] == 7


@posix_only
def test_a_silent_stage_is_stopped_with_its_whole_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    argv = _child(
        tmp_path,
        f"""
        import subprocess, sys, time
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(pid_file)!r}, "w").write(str(grandchild.pid))
        print("Epoch 0/5 itr 0/10: speed: 1.0(1.0s r0.0)s/itr", flush=True)
        time.sleep(60)
        """,
    )
    log_path = tmp_path / "train.log"
    started = time.monotonic()
    with pytest.raises(watch.StageStalled, match="no output for 1 s"):
        watch.run_watched_process(
            argv, cwd=tmp_path, env=dict(os.environ), log_path=log_path, stage="teacher-train",
            parser=watch.parse_exavatar_train_line, stall_seconds=1.0, poll_seconds=0.05,
        )
    assert time.monotonic() - started < 20
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(grandchild)
    progress = _read_progress(log_path)
    assert progress["state"] == "stalled" and progress["completed"] == 1
    assert _read_timing(log_path)[-1]["state"] == "stalled"


@posix_only
def test_steady_output_is_never_mistaken_for_a_stall(tmp_path: Path) -> None:
    argv = _child(
        tmp_path,
        """
        import time
        for itr in range(12):
            print("Epoch 0/1 itr %d/12: speed: 0.1(0.1s r0.0)s/itr" % itr, flush=True)
            time.sleep(0.1)
        """,
    )
    log_path = tmp_path / "train.log"
    code = watch.run_watched_process(
        argv, cwd=tmp_path, env=dict(os.environ), log_path=log_path, stage="teacher-train",
        parser=watch.parse_exavatar_train_line, stall_seconds=0.6, poll_seconds=0.05,
    )
    assert code == 0 and _read_progress(log_path)["state"] == "finished"


@posix_only
def test_an_error_in_the_reporter_never_stops_the_stage(tmp_path: Path) -> None:
    argv = _child(tmp_path, "import time; print('x', flush=True); time.sleep(0.3)")

    def broken(snapshot: dict) -> None:
        raise RuntimeError("reporter bug")

    code = watch.run_watched_process(
        argv, cwd=tmp_path, env=dict(os.environ), log_path=tmp_path / "s.log", stage="s",
        parser=None, stall_seconds=30, poll_seconds=0.02, write_seconds=0.0, report=broken,
    )
    assert code == 0


@posix_only
def test_an_interrupt_stops_the_stage_and_is_recorded(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    argv = _child(
        tmp_path,
        f"""
        import os, time
        open({str(pid_file)!r}, "w").write(str(os.getpid()))
        while True:
            print("tick", flush=True)
            time.sleep(0.05)
        """,
    )

    def interrupt(snapshot: dict) -> None:
        if pid_file.is_file():
            raise KeyboardInterrupt

    log_path = tmp_path / "s.log"
    with pytest.raises(KeyboardInterrupt):
        watch.run_watched_process(
            argv, cwd=tmp_path, env=dict(os.environ), log_path=log_path, stage="s",
            parser=None, stall_seconds=30, poll_seconds=0.05, write_seconds=0.0, report=interrupt,
        )
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child)
    assert _read_progress(log_path)["state"] == "stopped"
    assert _read_timing(log_path)[-1]["state"] == "stopped"


@posix_only
def test_sigterm_to_the_runner_stops_the_stage(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    runner = tmp_path / "runner.py"
    runner.write_text(
        textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {str(ROOT)!r})
            from pathlib import Path
            from bodyrig import photoreal_stage_watch as watch
            child = [sys.executable, "-c", "import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"]
            watch.run_watched_process(child, cwd=Path({str(tmp_path)!r}), env=dict(os.environ),
                log_path=Path({str(tmp_path / 'r.log')!r}), stage="r", parser=None,
                stall_seconds=60, poll_seconds=0.05)
            """
        ),
        encoding="utf-8",
    )
    import subprocess

    process = subprocess.Popen([sys.executable, str(runner)])
    deadline = time.monotonic() + 10
    while not pid_file.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.is_file()
    process.terminate()
    assert process.wait(timeout=45) == 128 + 15
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child)
    assert _read_progress(tmp_path / "r.log")["state"] == "stopped"


# --- the two callers ----------------------------------------------------------


@posix_only
def test_teacher_run_reports_a_stall_as_an_adapter_error_that_keeps_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _load_adapter()
    monkeypatch.setattr(adapter, "TEACHER_STALL_SECONDS", 0.5)
    monkeypatch.setattr(adapter, "TEACHER_POLL_SECONDS", 0.05)
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="snapshots are kept"):
        adapter._run(
            [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(30)"],
            cwd=tmp_path,
            log_path=tmp_path / "logs" / "teacher" / "train.log",
            label="ExAvatar teacher training",
            stage="teacher-train",
            parser=adapter.parse_exavatar_train_line,
        )
    assert _read_progress(tmp_path / "logs" / "teacher" / "train.log")["stage"] == "teacher-train"


@posix_only
def test_teacher_run_keeps_the_failure_message_and_log_tail(tmp_path: Path) -> None:
    adapter = _load_adapter()
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="failed with exit code 3: oops"):
        adapter._run(
            [sys.executable, "-c", "import sys; print('oops'); sys.exit(3)"],
            cwd=tmp_path,
            log_path=tmp_path / "neutral-pose.log",
            label="ExAvatar neutral-pose review rendering",
        )
    assert _read_timing(tmp_path / "neutral-pose.log")[-1]["stage"] == "neutral-pose"


def test_teacher_progress_report_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = _load_adapter()
    clock = [100.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    report = adapter._report_teacher_progress("teacher-train")
    report({"completed": None})
    report({"completed": 5, "total": 100, "eta_seconds": None})  # no measured rate yet
    report({"completed": 10, "total": 100, "percent": 10.0, "seconds_per_unit": 2.0, "eta_seconds": 180.0, "eta_utc": "x"})
    clock[0] += 60
    report({"completed": 40, "total": 100, "eta_seconds": 120.0})
    clock[0] += adapter.TEACHER_REPORT_SECONDS
    report({"completed": 90, "total": 100, "eta_seconds": None})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["completed"] for line in lines] == [10, 90]
    assert lines[0]["format"] == "bodyrig-exavatar-teacher-progress" and lines[0]["eta_seconds"] == 180.0


@posix_only
def test_preprocess_stage_stall_is_a_preprocess_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preprocess, "STAGE_STALL_SECONDS", 0.5)
    monkeypatch.setattr(preprocess, "STAGE_POLL_SECONDS", 0.05)
    with pytest.raises(preprocess.PhotorealExAvatarPreprocessError, match="re-run starts again at this stage"):
        preprocess._run_stage(
            [sys.executable, "-c", "import time; print('fit', flush=True); time.sleep(30)"],
            cwd=tmp_path,
            log_path=tmp_path / "logs" / "05-smplx-fit.log",
            label="ExAvatar SMPL-X fit stage",
        )
    assert _read_timing(tmp_path / "logs" / "05-smplx-fit.log")[-1]["stage"] == "05-smplx-fit"
