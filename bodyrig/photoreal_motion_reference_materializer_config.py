from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .photoreal_motion_reference_materializer import (
    ADAPTER,
    CONFIG_FORMAT,
    MAX_TIMEOUT_SECONDS,
    VERSION,
    PhotorealMotionReferenceMaterializerError,
)


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealMotionReferenceMaterializerError(f"{label} is invalid")
    return clean


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_motion_materializer_config(
    *,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    windows_python_path = Path(windows_python).expanduser().resolve()
    bridge = Path(bridge_path).expanduser().resolve()
    adapter = Path(adapter_path).expanduser().resolve()
    for path, label in (
        (windows_python_path, "Windows Python"),
        (bridge, "motion materializer WSL bridge"),
        (adapter, "motion materializer adapter"),
    ):
        if not path.is_file():
            raise PhotorealMotionReferenceMaterializerError(f"{label} not found: {path}")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    linux_python = _text(linux_python, label="Linux Python")
    if not linux_python.startswith("/"):
        raise PhotorealMotionReferenceMaterializerError("Linux Python must be an absolute Linux path")
    wsl_exe = _text(wsl_exe, label="WSL executable")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise PhotorealMotionReferenceMaterializerError(
            f"timeout_seconds must be an integer in 1..{MAX_TIMEOUT_SECONDS}"
        )
    return {
        "format": CONFIG_FORMAT,
        "version": VERSION,
        "adapter": ADAPTER,
        "revision": _hash_file(adapter),
        "command": [
            str(windows_python_path),
            str(bridge),
            "--distribution",
            distribution,
            "--wsl-exe",
            wsl_exe,
            "--linux-python",
            linux_python,
            "--adapter-path",
            str(adapter),
        ],
        "timeout_seconds": timeout_seconds,
    }


def build_motion_materializer_config_file(
    *,
    output_path: str | Path,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    result = build_motion_materializer_config(
        windows_python=windows_python,
        bridge_path=bridge_path,
        adapter_path=adapter_path,
        distribution=distribution,
        linux_python=linux_python,
        wsl_exe=wsl_exe,
        timeout_seconds=timeout_seconds,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealMotionReferenceMaterializerError(f"motion materializer config already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
