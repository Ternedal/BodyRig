#!/usr/bin/env python
"""Short target-rig probe for the Windows -> WSL recovery completion protocol."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from bodyrig.recover_cli import _run_wsl_file_protocol
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--external-python", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--descendant-seconds", type=int, default=20)
    args = parser.parse_args(argv)

    if not args.external_python.startswith("/"):
        parser.error("--external-python must be an absolute Linux path")
    if args.descendant_seconds < 10 or args.descendant_seconds > 120:
        parser.error("--descendant-seconds must be 10..120")

    converter = make_wsl_path_converter(args.wsl_exe, args.distribution)
    target_code = (
        "import json,subprocess,sys;"
        "json.load(sys.stdin);"
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep({args.descendant_seconds})']);"
        "json.dump({'ok':True,'descendant_pid':p.pid},sys.stdout);"
        "sys.stdout.write('\\n');sys.stdout.flush()"
    )
    request = {
        "format": "bodyrig-recovery-request",
        "version": 1,
        "sources": ["/tmp/bodyrig-completion-probe.mp4"],
    }

    started = time.monotonic()
    returncode, stdout, stderr, staging = _run_wsl_file_protocol(
        wsl_exe=args.wsl_exe,
        distribution=args.distribution,
        external_python=args.external_python,
        target_command=[args.external_python, "-c", target_code],
        request=request,
        converter=converter,
    )
    elapsed = time.monotonic() - started

    if returncode != 0:
        print(f"PROBE FAIL: target exit {returncode}; staging={staging}; stderr={stderr[-2000:]}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(stdout)
        descendant_pid = int(payload["descendant_pid"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"PROBE FAIL: invalid target result: {exc}; staging={staging}", file=sys.stderr)
        return 1

    alive = subprocess.run(
        [args.wsl_exe, "-d", args.distribution, "--", "kill", "-0", str(descendant_pid)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    subprocess.run(
        [args.wsl_exe, "-d", args.distribution, "--", "kill", str(descendant_pid)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    # The transport is allowed a 5s natural-exit grace period after the status
    # sentinel is published. It still must return well before the deliberately
    # surviving descendant's 20s default lifetime.
    limit = min(float(args.descendant_seconds) - 3.0, 10.0)
    if elapsed >= limit:
        print(f"PROBE FAIL: completion took {elapsed:.3f}s; limit={limit:.3f}s", file=sys.stderr)
        return 1
    if not alive:
        print("PROBE FAIL: descendant was not alive after completion returned", file=sys.stderr)
        return 1

    print(
        "PHYSICAL RECOVERY COMPLETION: PASS | "
        f"elapsed={elapsed:.3f}s | descendant_pid={descendant_pid} | "
        "sentinel=bodyrig-file-command-status-v1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
