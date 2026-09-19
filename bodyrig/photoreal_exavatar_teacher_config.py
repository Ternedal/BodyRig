from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_exavatar_teacher_wsl_bridge import (
    PhotorealExAvatarTeacherWslError,
    build_teacher_transport_revision,
)

FORMAT = "bodyrig-photoreal-teacher-config"
VERSION = 1
ADAPTER = "exavatar-benchmark"
UPSTREAM_REPOSITORY = "https://github.com/mks0601/ExAvatar_RELEASE"
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
MAX_TIMEOUT_SECONDS = 604800


class PhotorealExAvatarTeacherConfigError(ValueError):
    pass


def _strict_json_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarTeacherConfigError(f"{label} is invalid")
    return result


def _absolute_linux(value: Any, *, label: str) -> str:
    result = _text(value, label=label)
    if not result.startswith("/") or result == "/":
        raise PhotorealExAvatarTeacherConfigError(f"{label} must be a non-root absolute Linux path")
    return result


def build_exavatar_teacher_config(
    *,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    linux_workspace_root: str,
    linux_runtime_preflight: str,
    linux_python: str = "/opt/bodyrig-exavatar/bin/python",
    distribution: str = "Ubuntu-22.04",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    windows_python_path = Path(windows_python).expanduser().resolve()
    bridge = Path(bridge_path).expanduser().resolve()
    adapter = Path(adapter_path).expanduser().resolve()
    if not windows_python_path.is_file():
        raise PhotorealExAvatarTeacherConfigError(f"Windows Python not found: {windows_python_path}")
    if not bridge.is_file():
        raise PhotorealExAvatarTeacherConfigError(f"ExAvatar teacher WSL bridge not found: {bridge}")
    if not adapter.is_file():
        raise PhotorealExAvatarTeacherConfigError(f"ExAvatar teacher adapter not found: {adapter}")

    workspace = _absolute_linux(linux_workspace_root, label="Linux workspace root")
    runtime_preflight = _absolute_linux(linux_runtime_preflight, label="Linux runtime preflight")
    linux_python = _absolute_linux(linux_python, label="Linux Python")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    wsl_exe = _text(wsl_exe, label="WSL executable", maximum=4096)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise PhotorealExAvatarTeacherConfigError(
            f"timeout_seconds must be an integer in 1..{MAX_TIMEOUT_SECONDS}"
        )

    try:
        revision = build_teacher_transport_revision(bridge_path=bridge, adapter_path=adapter)
    except PhotorealExAvatarTeacherWslError as exc:
        raise PhotorealExAvatarTeacherConfigError(str(exc)) from exc

    return {
        "format": FORMAT,
        "version": VERSION,
        "adapter": ADAPTER,
        "revision": revision,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": UPSTREAM_COMMIT,
        "command": [
            str(windows_python_path),
            str(bridge),
            "--distribution",
            distribution,
            "--wsl-exe",
            wsl_exe,
            "--linux-python",
            linux_python,
            "--workspace-root",
            workspace,
            "--runtime-preflight",
            runtime_preflight,
            "--adapter-script",
            str(adapter),
        ],
        "timeout_seconds": timeout_seconds,
    }


def validate_exavatar_teacher_config_file(
    *,
    config_path: str | Path,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    linux_workspace_root: str,
    linux_runtime_preflight: str,
    linux_python: str = "/opt/bodyrig-exavatar/bin/python",
    distribution: str = "Ubuntu-22.04",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    source = Path(config_path).expanduser().resolve()
    try:
        existing = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarTeacherConfigError(f"teacher config is unreadable: {source}") from exc
    if not isinstance(existing, dict):
        raise PhotorealExAvatarTeacherConfigError("teacher config must be a JSON object")
    expected = build_exavatar_teacher_config(
        windows_python=windows_python,
        bridge_path=bridge_path,
        adapter_path=adapter_path,
        linux_workspace_root=linux_workspace_root,
        linux_runtime_preflight=linux_runtime_preflight,
        linux_python=linux_python,
        distribution=distribution,
        wsl_exe=wsl_exe,
        timeout_seconds=timeout_seconds,
    )
    if not _strict_json_equal(existing, expected):
        raise PhotorealExAvatarTeacherConfigError(
            "existing teacher config does not match the current bridge/adapter/runtime authority"
        )
    return existing


def build_exavatar_teacher_config_file(
    *,
    output_path: str | Path,
    windows_python: str | Path,
    bridge_path: str | Path,
    adapter_path: str | Path,
    linux_workspace_root: str,
    linux_runtime_preflight: str,
    linux_python: str = "/opt/bodyrig-exavatar/bin/python",
    distribution: str = "Ubuntu-22.04",
    wsl_exe: str = "wsl.exe",
    timeout_seconds: int = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    result = build_exavatar_teacher_config(
        windows_python=windows_python,
        bridge_path=bridge_path,
        adapter_path=adapter_path,
        linux_workspace_root=linux_workspace_root,
        linux_runtime_preflight=linux_runtime_preflight,
        linux_python=linux_python,
        distribution=distribution,
        wsl_exe=wsl_exe,
        timeout_seconds=timeout_seconds,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealExAvatarTeacherConfigError(f"teacher config output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
