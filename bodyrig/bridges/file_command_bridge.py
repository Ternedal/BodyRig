#!/usr/bin/env python
"""Run one command with file-backed stdio and publish an atomic completion status.

This bridge runs inside the target environment (WSL in production) so no Windows
stdio file handle crosses the Windows -> WSL boundary. The status file is the
authoritative completion sentinel and is published only after the child process
has returned and its file-backed stdout/stderr handles have closed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

STATUS_FORMAT = "bodyrig-file-command-status"
STATUS_VERSION = 1


def _atomic_json(path: Path, payload: dict) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = raw.index("--")
    except ValueError:
        print("BodyRig file command bridge: missing -- command separator", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--stdin-file", required=True)
    parser.add_argument("--stdout-file", required=True)
    parser.add_argument("--stderr-file", required=True)
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args(raw[:separator])
    command = raw[separator + 1 :]
    if not command:
        print("BodyRig file command bridge: command is empty", file=sys.stderr)
        return 2

    stdin_path = Path(args.stdin_file).expanduser().resolve()
    stdout_path = Path(args.stdout_file).expanduser().resolve()
    stderr_path = Path(args.stderr_file).expanduser().resolve()
    status_path = Path(args.status_file).expanduser().resolve()
    if not stdin_path.is_file():
        print(f"BodyRig file command bridge: stdin file not found: {stdin_path}", file=sys.stderr)
        return 2
    for path in (stdout_path, stderr_path, status_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            print(f"BodyRig file command bridge: refusing existing output: {path}", file=sys.stderr)
            return 2

    returncode = 127
    try:
        with (
            stdin_path.open("rb") as stdin_file,
            stdout_path.open("xb") as stdout_file,
            stderr_path.open("xb") as stderr_file,
        ):
            completed = subprocess.run(
                command,
                stdin=stdin_file,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
            )
            returncode = int(completed.returncode)
    except Exception as exc:
        try:
            with stderr_path.open("ab") as stderr_file:
                stderr_file.write(
                    f"\nBodyRig file command bridge: {exc}\n".encode("utf-8", errors="replace")
                )
        except OSError:
            pass
    finally:
        _atomic_json(
            status_path,
            {
                "format": STATUS_FORMAT,
                "version": STATUS_VERSION,
                "returncode": returncode,
            },
        )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
