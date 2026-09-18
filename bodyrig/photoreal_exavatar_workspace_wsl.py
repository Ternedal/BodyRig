from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

FORMAT = "bodyrig-photoreal-exavatar-workspace"
VERSION = 1


class PhotorealExAvatarWorkspaceWslError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealExAvatarWorkspaceWslError(f"{label} is invalid")
    return result


def _run(invocation: list[str], *, label: str) -> subprocess.CompletedProcess[str]:
    try:
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
    except OSError as exc:
        raise PhotorealExAvatarWorkspaceWslError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stdout or "")[-8000:].strip()
        raise PhotorealExAvatarWorkspaceWslError(
            f"{label} failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
        )
    return completed


def _read_linux_json(*, wsl_exe: str, distribution: str, path: str) -> dict[str, Any]:
    completed = _run(
        [wsl_exe, "-d", distribution, "--", "/bin/cat", path],
        label="read ExAvatar workspace receipt",
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt is not valid JSON") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt must be a JSON object")
    return value


def prepare_exavatar_workspace_wsl(
    *,
    materialized_dataset_dir: str | Path,
    materialization_receipt_path: str | Path,
    strict_preflight_path: str | Path,
    linux_dependency_root: str,
    asset_root: str | Path,
    reference_model_root: str | Path,
    linux_workspace_root: str,
    smplx_gender: str,
    distribution: str = "Ubuntu-22.04",
    linux_python: str = "/opt/bodyrig-photoreal/bin/python",
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    dependency_root = _text(linux_dependency_root, label="Linux dependency root")
    workspace_root = _text(linux_workspace_root, label="Linux workspace root")
    linux_python = _text(linux_python, label="Linux Python")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    gender = str(smplx_gender or "").strip().lower()
    if gender not in {"female", "male", "neutral"}:
        raise PhotorealExAvatarWorkspaceWslError("smplx_gender must be explicitly female, male or neutral")
    for label, value in (
        ("Linux dependency root", dependency_root),
        ("Linux workspace root", workspace_root),
        ("Linux Python", linux_python),
    ):
        if not value.startswith("/"):
            raise PhotorealExAvatarWorkspaceWslError(f"{label} must be an absolute Linux path")
    if workspace_root == "/":
        raise PhotorealExAvatarWorkspaceWslError("Linux workspace root may not be '/'")

    dataset = Path(materialized_dataset_dir).expanduser().resolve()
    materialization = Path(materialization_receipt_path).expanduser().resolve()
    preflight = Path(strict_preflight_path).expanduser().resolve()
    assets = Path(asset_root).expanduser().resolve()
    reference = Path(reference_model_root).expanduser().resolve()
    if not dataset.is_dir():
        raise PhotorealExAvatarWorkspaceWslError(f"materialized dataset not found: {dataset}")
    for label, path in (
        ("materialization receipt", materialization),
        ("strict preflight receipt", preflight),
    ):
        if not path.is_file():
            raise PhotorealExAvatarWorkspaceWslError(f"{label} not found: {path}")
    for label, path in (("asset root", assets), ("reference model root", reference)):
        if not path.is_dir():
            raise PhotorealExAvatarWorkspaceWslError(f"{label} not found: {path}")

    repo_root = Path(__file__).resolve().parents[1]
    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        linux_dataset = converter(str(dataset))
        linux_materialization = converter(str(materialization))
        linux_preflight = converter(str(preflight))
        linux_assets = converter(str(assets))
        linux_reference = converter(str(reference))
        linux_repo = converter(str(repo_root))
    except (OSError, WslBridgeError) as exc:
        raise PhotorealExAvatarWorkspaceWslError(f"ExAvatar workspace path transport failed: {exc}") from exc

    invocation = [
        wsl_exe,
        "-d",
        distribution,
        "--",
        "/usr/bin/env",
        f"PYTHONPATH={linux_repo}",
        linux_python,
        "-m",
        "bodyrig.photoreal_exavatar_workspace_cli",
        "--materialized-dataset-dir",
        linux_dataset,
        "--materialization-receipt",
        linux_materialization,
        "--strict-preflight",
        linux_preflight,
        "--dependency-root",
        dependency_root,
        "--asset-root",
        linux_assets,
        "--reference-model-root",
        linux_reference,
        "--workspace-root",
        workspace_root,
        "--smplx-gender",
        gender,
    ]
    completed = _run(invocation, label="ExAvatar workspace preparation")
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")

    receipt = _read_linux_json(
        wsl_exe=wsl_exe,
        distribution=distribution,
        path=workspace_root.rstrip("/") + "/workspace-receipt.json",
    )
    if receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt format/version mismatch")
    if receipt.get("smplx_gender") != gender or receipt.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt gender provenance mismatch")
    if receipt.get("dataset") != "Custom" or receipt.get("upstream_default_gender_accepted") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt config patch mismatch")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace disclosed forbidden source/eval data")
    if receipt.get("dependency_root_modified") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace modified pinned dependency root")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace crossed downstream authority")
    return receipt
