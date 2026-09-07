from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Callable

EXPECTED_PYTHON = (3, 11)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_EXACT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$")
_REQUIRED_DISTS = {
    "fastapi",
    "uvicorn",
    "pydantic",
    "pillow",
    "pytest",
    "httpx",
    "httpx2",
}


class RuntimeLockError(ValueError):
    pass


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lock(path: str | Path) -> dict[str, str]:
    lock_path = Path(path).expanduser().resolve()
    if not lock_path.is_file():
        raise RuntimeLockError(f"runtime lock not found: {lock_path}")
    try:
        lines = lock_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise RuntimeLockError(f"runtime lock is unreadable: {lock_path}") from exc

    packages: dict[str, str] = {}
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _EXACT_RE.fullmatch(line)
        if match is None:
            raise RuntimeLockError(
                f"runtime lock line {line_number} must be an exact name==version pin"
            )
        name_raw, version = match.groups()
        if not _NAME_RE.fullmatch(name_raw):
            raise RuntimeLockError(f"runtime lock line {line_number} has invalid package name")
        name = _normalize_name(name_raw)
        if name in packages:
            raise RuntimeLockError(f"runtime lock contains duplicate package: {name}")
        packages[name] = version

    if not packages:
        raise RuntimeLockError("runtime lock contains no package pins")
    missing = sorted(_REQUIRED_DISTS - packages.keys())
    if missing:
        raise RuntimeLockError(
            "runtime lock is missing required BodyRig distributions: " + ", ".join(missing)
        )
    return packages


def validate_runtime(
    path: str | Path,
    *,
    expected_python: tuple[int, int] = EXPECTED_PYTHON,
    version_reader: Callable[[str], str] = importlib.metadata.version,
) -> dict[str, object]:
    lock_path = Path(path).expanduser().resolve()
    if sys.version_info[:2] != expected_python:
        raise RuntimeLockError(
            f"BodyRig rig runtime requires Python {expected_python[0]}.{expected_python[1]}; "
            f"running {sys.version_info.major}.{sys.version_info.minor}"
        )

    expected = load_lock(lock_path)
    installed: dict[str, str] = {}
    mismatches: list[str] = []
    for name, wanted in sorted(expected.items()):
        try:
            actual = version_reader(name)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {wanted})")
            continue
        installed[name] = actual
        if actual != wanted:
            mismatches.append(f"{name}: {actual} != {wanted}")

    if mismatches:
        raise RuntimeLockError(
            "BodyRig Windows Python runtime differs from canonical lock: "
            + "; ".join(mismatches)
        )

    return {
        "format": "bodyrig-windows-python-runtime-lock",
        "version": 1,
        "python": {
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "micro": sys.version_info.micro,
            "executable": str(Path(sys.executable).resolve()),
        },
        "lock": {
            "path": str(lock_path),
            "sha256": _sha256(lock_path),
            "package_count": len(expected),
        },
        "packages": installed,
        "ok": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify BodyRig's canonical Windows Python operator runtime."
    )
    parser.add_argument("--lock", required=True)
    args = parser.parse_args(argv)
    try:
        value = validate_runtime(args.lock)
    except RuntimeLockError as exc:
        print(f"BodyRig Windows Python runtime: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
