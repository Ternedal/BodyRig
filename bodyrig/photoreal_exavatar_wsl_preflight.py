from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

FORMAT = "bodyrig-photoreal-exavatar-preflight"
VERSION = 1


class PhotorealExAvatarWslPreflightError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarWslPreflightError(f"ExAvatar preflight receipt is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight receipt must be a JSON object")
    return value


def _text(value: str, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarWslPreflightError(f"{label} is invalid")
    return result


def run_exavatar_wsl_preflight(
    *,
    dependency_root: str,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    output_path: str | Path,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
    require_colmap: bool = True,
) -> dict[str, Any]:
    dependency_root = _text(dependency_root, label="Linux dependency root")
    if not dependency_root.startswith("/"):
        raise PhotorealExAvatarWslPreflightError("Linux dependency root must be absolute")
    linux_python = _text(linux_python, label="Linux Python")
    if not linux_python.startswith("/"):
        raise PhotorealExAvatarWslPreflightError("Linux Python must be absolute")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    gender = str(smplx_gender or "").strip().lower()
    if gender not in {"female", "male", "neutral"}:
        raise PhotorealExAvatarWslPreflightError("smplx_gender must be explicitly female, male or neutral")

    asset_path = Path(asset_root).expanduser().resolve()
    reference_path = Path(reference_model_root).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not asset_path.is_dir():
        raise PhotorealExAvatarWslPreflightError(f"ExAvatar asset root not found: {asset_path}")
    if not reference_path.is_dir():
        raise PhotorealExAvatarWslPreflightError(f"reference model root not found: {reference_path}")
    if output.exists():
        raise PhotorealExAvatarWslPreflightError(f"ExAvatar preflight output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]

    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_assets = converter(str(asset_path))
        linux_reference = converter(str(reference_path))
        linux_output = converter(str(output))
        linux_repo = converter(str(repo_root))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealExAvatarWslPreflightError(f"ExAvatar preflight path transport failed: {exc}") from exc

    invocation = [
        wsl_exe,
        "-d",
        distribution,
        "--",
        "/usr/bin/env",
        f"PYTHONPATH={linux_repo}",
        linux_python,
        "-m",
        "bodyrig.photoreal_exavatar_preflight_cli",
        "--dependency-root",
        dependency_root,
        "--asset-root",
        linux_assets,
        "--reference-model-root",
        linux_reference,
        "--smplx-gender",
        gender,
        "--out",
        linux_output,
    ]
    if not require_colmap:
        invocation.append("--no-colmap")
    completed = subprocess.run(
        invocation,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.returncode not in {0, 2}:
        detail = (completed.stdout or "")[-6000:].strip()
        raise PhotorealExAvatarWslPreflightError(
            f"ExAvatar WSL preflight failed with exit code {completed.returncode}" + (f": {detail}" if detail else "")
        )
    if not output.is_file():
        raise PhotorealExAvatarWslPreflightError("ExAvatar WSL preflight did not create its receipt")
    result = _read_json(output)
    if result.get("format") != FORMAT or result.get("version") != VERSION:
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight receipt format/version mismatch")
    if result.get("smplx_gender") != gender or result.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight receipt gender provenance mismatch")
    if result.get("automatic_restricted_asset_download") is not False:
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight unexpectedly enabled restricted asset download")
    if result.get("photoreal_acceptance_authority") is not False or result.get("production_activation") is not False:
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight crossed downstream authority")
    ready = result.get("benchmark_environment_ready") is True
    if (completed.returncode == 0) != ready:
        raise PhotorealExAvatarWslPreflightError("ExAvatar preflight process/receipt readiness disagree")
    return result
