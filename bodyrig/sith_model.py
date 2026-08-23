from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence


class SithModelError(RuntimeError):
    pass


_TREE_DIGEST_SCRIPT = r'''
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
if not root.is_absolute() or not root.is_dir():
    raise SystemExit("model path is not an absolute directory")
files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix())
if not 1 <= len(files) <= 20000:
    raise SystemExit("model tree must contain 1..20000 files")
h = hashlib.sha256()
total = 0
for path in files:
    rel = path.relative_to(root).as_posix().encode("utf-8")
    size = path.stat().st_size
    total += size
    h.update(len(rel).to_bytes(4, "big"))
    h.update(rel)
    h.update(size.to_bytes(8, "big"))
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
print(json.dumps({"sha256": h.hexdigest(), "file_count": len(files), "byte_count": total}, separators=(",", ":")))
'''


def _run_wsl(
    *,
    wsl_exe: str,
    distribution: str,
    command: Sequence[str],
    timeout: int = 7200,
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


def digest_model_tree(
    *,
    distribution: str,
    python: str,
    model_path: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    for label, value in (
        ("distribution", distribution),
        ("python", python),
        ("model_path", model_path),
        ("wsl_exe", wsl_exe),
    ):
        if not isinstance(value, str) or not value.strip():
            raise SithModelError(f"SiTH model {label} is required")
    if not python.startswith("/") or not model_path.startswith("/"):
        raise SithModelError("SiTH model Python/path must be absolute Linux paths")
    try:
        completed = _run_wsl(
            wsl_exe=wsl_exe,
            distribution=distribution,
            command=[python, "-c", _TREE_DIGEST_SCRIPT, model_path],
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SithModelError("SiTH diffusion model digest could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1500:]
        raise SithModelError(f"SiTH diffusion model digest failed: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SithModelError("SiTH diffusion model digest returned invalid JSON") from exc
    if not isinstance(result, dict) or set(result) != {"sha256", "file_count", "byte_count"}:
        raise SithModelError("SiTH diffusion model digest fields are invalid")
    digest = result["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise SithModelError("SiTH diffusion model digest is invalid")
    for field in ("file_count", "byte_count"):
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SithModelError(f"SiTH diffusion model {field} is invalid")
    if result["file_count"] > 20000:
        raise SithModelError("SiTH diffusion model file_count exceeds limit")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute a deterministic byte-bound digest for a local SiTH diffusion model tree.")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        result = digest_model_tree(
            distribution=args.distribution,
            python=args.python,
            model_path=args.model_path,
            wsl_exe=args.wsl_exe,
        )
    except SithModelError as exc:
        print(f"BodyRig SiTH model digest: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
