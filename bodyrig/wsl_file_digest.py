from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from typing import Any, Sequence


class WslFileDigestError(RuntimeError):
    pass


_DIGEST_SCRIPT = r'''
import hashlib, json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.is_absolute() or not path.is_file():
    raise SystemExit("file path is not an absolute regular file")
h = hashlib.sha256()
size = 0
with path.open("rb") as stream:
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        h.update(chunk)
print(json.dumps({"sha256": h.hexdigest(), "byte_count": size}, separators=(",", ":")))
'''


def _run_wsl(
    *,
    wsl_exe: str,
    distribution: str,
    command: Sequence[str],
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [wsl_exe, "-d", distribution, "--", *command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def digest_wsl_file(
    *,
    distribution: str,
    python: str,
    path: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    for label, value in (
        ("distribution", distribution),
        ("python", python),
        ("path", path),
        ("wsl_exe", wsl_exe),
    ):
        if not isinstance(value, str) or not value.strip():
            raise WslFileDigestError(f"WSL file digest {label} is required")
    if not python.startswith("/") or not path.startswith("/"):
        raise WslFileDigestError("WSL file digest Python/path must be absolute Linux paths")

    try:
        completed = _run_wsl(
            wsl_exe=wsl_exe,
            distribution=distribution.strip(),
            command=[python, "-c", _DIGEST_SCRIPT, path],
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WslFileDigestError("WSL file digest could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1500:]
        raise WslFileDigestError(f"WSL file digest failed: {detail}")

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WslFileDigestError("WSL file digest returned invalid JSON") from exc
    if not isinstance(result, dict) or set(result) != {"sha256", "byte_count"}:
        raise WslFileDigestError("WSL file digest fields are invalid")
    digest = result["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise WslFileDigestError("WSL file digest SHA-256 is invalid")
    byte_count = result["byte_count"]
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
        raise WslFileDigestError("WSL file digest byte_count is invalid")
    return {"sha256": digest, "byte_count": byte_count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute a deterministic SHA-256 for one regular file inside WSL.")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = digest_wsl_file(
            distribution=args.distribution,
            python=args.python,
            path=args.path,
            wsl_exe=args.wsl_exe,
        )
    except WslFileDigestError as exc:
        print(f"BodyRig WSL file digest: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
