"""Run one child process under wall-clock, memory and process-tree bounds.

Used for workers that read untrusted input (the Blender scene inspector). What
it enforces, per platform, and nothing more:

Windows
    The child is created suspended, assigned to a Job Object and then resumed,
    so it and everything it spawns live in the job from the first instruction.
    The job has KILL_ON_JOB_CLOSE (closing the handle kills the whole tree), a
    committed-memory limit for the whole job, an active-process limit, below-
    normal priority, and UI restrictions (no clipboard, no desktop/display
    changes, no foreign USER handles). Network and file-system access are NOT
    restricted by a job object.

POSIX
    The child gets its own session, so a timeout kills the whole process group.
    RLIMIT_CORE=0 and an RLIMIT_CPU ceiling are applied right after spawn with
    ``resource.prlimit`` (Linux), nice 10, and a resident-memory watchdog kills
    the group when the summed RSS of the group exceeds the limit (Linux /proc).
    ``preexec_fn`` is deliberately not used: callers run several workers from
    threads, where ``preexec_fn`` can deadlock.

Network and file-system isolation on Linux/WSL2 come from an optional
bubblewrap prefix built by the caller (``bodyrig.scene_inspector``); this
module only runs the argv it is given.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

POLL_SECONDS = 0.1


class CancelledRun(Exception):
    """The caller's cancel event was set; the child tree has already been killed."""


@dataclass(frozen=True)
class Limits:
    wall_seconds: float
    memory_bytes: int | None = None
    cpu_seconds: int | None = None
    max_processes: int = 8
    below_normal_priority: bool = True


@dataclass
class BoundedResult:
    returncode: int | None
    timed_out: bool
    memory_exceeded: bool
    wall_ms: int
    peak_memory_bytes: int | None
    applied: dict[str, Any] = field(default_factory=dict)


# --- Windows job objects ---------------------------------------------------------------

if os.name == "nt":  # pragma: no cover - exercised on the Windows CI runner
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    JOB_OBJECT_BASIC_UI_RESTRICTIONS_CLASS = 4
    JOB_OBJECT_UILIMIT_ALL = 0x000000FF
    BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
    CREATE_SUSPENDED = 0x00000004
    CREATE_NO_WINDOW = 0x08000000
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    PROCESS_SUSPEND_RESUME = 0x0800

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _UiRestrictions(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    def _check(ok: Any, what: str) -> None:
        if not ok:
            raise OSError(ctypes.get_last_error(), f"{what} failed")

    def _create_job(limits: Limits) -> Any:
        job = _kernel32.CreateJobObjectW(None, None)
        _check(job, "CreateJobObjectW")
        info = _ExtendedLimit()
        flags = (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
                 | JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        info.BasicLimitInformation.ActiveProcessLimit = max(1, limits.max_processes)
        if limits.below_normal_priority:
            flags |= JOB_OBJECT_LIMIT_PRIORITY_CLASS
            info.BasicLimitInformation.PriorityClass = BELOW_NORMAL_PRIORITY_CLASS
        if limits.memory_bytes:
            flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = limits.memory_bytes
        info.BasicLimitInformation.LimitFlags = flags
        _check(_kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                 ctypes.byref(info), ctypes.sizeof(info)), "SetInformationJobObject")
        ui = _UiRestrictions(JOB_OBJECT_UILIMIT_ALL)
        _check(_kernel32.SetInformationJobObject(job, JOB_OBJECT_BASIC_UI_RESTRICTIONS_CLASS,
                                                 ctypes.byref(ui), ctypes.sizeof(ui)), "SetInformationJobObject(UI)")
        return job

    def _job_peak(job: Any) -> int | None:
        info = _ExtendedLimit()
        ok = _kernel32.QueryInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                 ctypes.byref(info), ctypes.sizeof(info), None)
        return int(info.PeakJobMemoryUsed) if ok else None


def _linux_processes() -> dict[int, tuple[int, int, int, int]]:
    """pid -> (ppid, pgrp, start_time_ticks, rss_bytes) from /proc; empty where /proc is missing."""
    found: dict[int, tuple[int, int, int, int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    page = os.sysconf("SC_PAGE_SIZE")
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as handle:
                fields = handle.read().rsplit(b")", 1)[1].split()
            # fields[0] is stat field 3 (state): ppid=4, pgrp=5, starttime=22, rss=24
            found[int(entry)] = (int(fields[1]), int(fields[2]), int(fields[19]), int(fields[21]) * page)
        except (OSError, ValueError, IndexError):
            continue
    return found


def _descendants(root: int, procs: Mapping[int, tuple[int, int, int, int]]) -> set[int]:
    """``root``, everything below it by parent pid, and its process group.

    Parent links matter because a descendant may start its own session
    (bubblewrap ``--new-session`` does), which takes it out of the group.
    """
    children: dict[int, list[int]] = {}
    for pid, (ppid, _pgrp, _start, _rss) in procs.items():
        children.setdefault(ppid, []).append(pid)
    tree = {root} | {pid for pid, info in procs.items() if info[1] == root}
    stack = list(tree)
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in tree:
                tree.add(child)
                stack.append(child)
    return tree


def _kill_posix_tree(root: int, seen: dict[int, int]) -> None:
    """SIGKILL the group, the live tree, and every process seen in the tree that still has its start time."""
    import signal

    try:
        os.killpg(root, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    for _ in range(2):  # a second pass catches children forked during the first
        procs = _linux_processes()
        targets = {pid: procs[pid][2] for pid in _descendants(root, procs) if pid in procs}
        targets.update({pid: start for pid, start in seen.items() if pid in procs and procs[pid][2] == start})
        for pid in targets:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _poll_hook(callback: Any) -> None:
    if callback is not None:
        try:
            callback()
        except Exception:  # a progress relay must never break supervision
            pass


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str],
    limits: Limits,
    stdout_path: str | Path,
    stderr_path: str | Path,
    cancel: Any = None,
    on_poll: Any = None,
) -> BoundedResult:
    """Run ``argv`` to completion or until a limit is hit. Never raises for child failure.

    ``cancel`` is an optional ``threading.Event``; when it is set the whole child
    tree is killed and :class:`CancelledRun` is raised (a batch's Ctrl+C).
    ``on_poll`` is called once per poll while the child runs (progress relay);
    an exception from it is ignored, so it can never weaken the supervision.
    """
    started = time.perf_counter()
    applied: dict[str, Any] = {"platform": sys.platform, "wall_seconds": limits.wall_seconds}
    timed_out = memory_exceeded = False
    peak: int | None = None
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        if os.name == "nt":  # pragma: no cover - exercised on the Windows CI runner
            job = _create_job(limits)
            try:
                proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL,
                                        stdout=out, stderr=err, creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW)
                handle = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME,
                                               False, proc.pid)
                try:
                    _check(handle, "OpenProcess")
                    if not _kernel32.AssignProcessToJobObject(job, handle):
                        proc.kill()
                        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
                    if _ntdll.NtResumeProcess(handle) != 0:
                        _kernel32.TerminateJobObject(job, 1)
                        raise OSError("NtResumeProcess failed")
                finally:
                    if handle:
                        _kernel32.CloseHandle(handle)
                applied.update({"job_object": True, "kill_on_close": True, "ui_restricted": True,
                                "job_memory_bytes": limits.memory_bytes, "max_processes": limits.max_processes,
                                "below_normal_priority": limits.below_normal_priority})
                deadline = started + limits.wall_seconds
                try:
                    while proc.poll() is None:
                        if cancel is not None and cancel.is_set():
                            raise CancelledRun("cancelled")
                        if time.perf_counter() >= deadline:
                            timed_out = True
                            _kernel32.TerminateJobObject(job, 1)
                            proc.wait()
                            break
                        _poll_hook(on_poll)
                        time.sleep(POLL_SECONDS)
                except BaseException:  # cancelled (event, Ctrl+C, shutdown): never leave the tree running
                    _kernel32.TerminateJobObject(job, 1)
                    proc.wait()
                    raise
                peak = _job_peak(job)
                if limits.memory_bytes and peak is not None and peak >= int(limits.memory_bytes * 0.98):
                    memory_exceeded = proc.returncode != 0
            finally:
                _kernel32.CloseHandle(job)
        else:
            proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True)
            pgid = proc.pid
            applied["process_group_kill"] = True
            try:
                import resource

                if hasattr(resource, "prlimit"):
                    resource.prlimit(proc.pid, resource.RLIMIT_CORE, (0, 0))
                    if limits.cpu_seconds:
                        resource.prlimit(proc.pid, resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 5))
                    applied.update({"core_dumps": False, "cpu_seconds": limits.cpu_seconds})
                if limits.below_normal_priority:
                    os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
                    applied["nice"] = 10
            except (OSError, ValueError):
                applied["rlimits_partial"] = True
            have_proc = os.path.isdir("/proc")
            watch_rss = limits.memory_bytes is not None and have_proc
            applied["rss_watchdog_bytes"] = limits.memory_bytes if watch_rss else None
            applied["tree_kill"] = "group+descendants" if have_proc else "group"
            deadline = started + limits.wall_seconds
            peak = 0 if watch_rss else None
            seen: dict[int, int] = {}  # pid -> start time, for descendants orphaned before the end
            try:
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise CancelledRun("cancelled")
                    if have_proc:
                        procs = _linux_processes()
                        tree = _descendants(pgid, procs)
                        seen.update({pid: procs[pid][2] for pid in tree if pid in procs})
                        if watch_rss:
                            rss = sum(procs[pid][3] for pid in tree if pid in procs)
                            peak = max(peak or 0, rss)
                            if rss > limits.memory_bytes:
                                memory_exceeded = True
                                _kill_posix_tree(pgid, seen)
                                break
                    if time.perf_counter() >= deadline:
                        timed_out = True
                        _kill_posix_tree(pgid, seen)
                        break
                    _poll_hook(on_poll)
                    time.sleep(POLL_SECONDS)
            except BaseException:  # cancelled (Ctrl+C, shutdown): the child has its own session, so kill it here
                _kill_posix_tree(pgid, seen)
                proc.wait()
                raise
            proc.wait()
            _kill_posix_tree(pgid, seen)  # no stragglers from a child that exited first
    return BoundedResult(
        returncode=proc.returncode,
        timed_out=timed_out,
        memory_exceeded=memory_exceeded,
        wall_ms=int(round((time.perf_counter() - started) * 1000)),
        peak_memory_bytes=peak,
        applied=applied,
    )


def tail(path: str | Path, limit: int = 4000) -> str:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace")


__all__ = ["BoundedResult", "CancelledRun", "Limits", "run_bounded", "tail"]
