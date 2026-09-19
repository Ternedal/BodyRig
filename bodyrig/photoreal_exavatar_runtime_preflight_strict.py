from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_exavatar_runtime_preflight import (
    PhotorealExAvatarRuntimePreflightError,
    build_runtime_preflight,
)
from .photoreal_exavatar_runtime_setup_receipt import (
    PhotorealExAvatarRuntimeSetupReceiptError,
    validate_runtime_setup_receipt,
)


class PhotorealExAvatarRuntimePreflightStrictError(PhotorealExAvatarRuntimePreflightError):
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


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_runtime_preflight_strict(*, workspace_root: str | Path) -> dict[str, Any]:
    try:
        setup = validate_runtime_setup_receipt(linux_python=sys.executable)
    except PhotorealExAvatarRuntimeSetupReceiptError as exc:
        raise PhotorealExAvatarRuntimePreflightStrictError(f"pinned ExAvatar runtime setup gate failed: {exc}") from exc
    result = build_runtime_preflight(workspace_root=workspace_root)
    if str(result.get("python_executable") or "") != str(Path(sys.executable).resolve()):
        raise PhotorealExAvatarRuntimePreflightStrictError("runtime preflight Python provenance mismatch")
    setup_sha = str(setup.get("setup_sha256") or "").strip().lower()
    if len(setup_sha) != 64 or any(ch not in "0123456789abcdef" for ch in setup_sha):
        raise PhotorealExAvatarRuntimePreflightStrictError("runtime setup SHA-256 is invalid")
    result["runtime_setup_sha256"] = setup_sha
    result["runtime_setup_provenance_verified"] = True
    result["runtime_preflight_sha256"] = _digest(result, omit="runtime_preflight_sha256")
    return result


def validate_runtime_preflight_strict_file(
    *,
    workspace_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    try:
        existing = json.loads(output.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarRuntimePreflightStrictError(
            f"runtime preflight output is unreadable: {output}"
        ) from exc
    if not isinstance(existing, dict):
        raise PhotorealExAvatarRuntimePreflightStrictError(
            "runtime preflight output must be a JSON object"
        )
    expected = build_runtime_preflight_strict(workspace_root=workspace_root)
    if not _strict_json_equal(existing, expected):
        raise PhotorealExAvatarRuntimePreflightStrictError(
            "existing runtime preflight does not match the current pinned runtime/workspace"
        )
    return existing


def build_runtime_preflight_strict_file(*, workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    result = build_runtime_preflight_strict(workspace_root=workspace_root)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealExAvatarRuntimePreflightStrictError(f"runtime preflight output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
