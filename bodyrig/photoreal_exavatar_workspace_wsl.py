from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .wsl_adapter_bridge import WslBridgeError, make_wsl_path_converter

FORMAT = "bodyrig-photoreal-exavatar-workspace"
VERSION = 1


class PhotorealExAvatarWorkspaceWslError(ValueError):
    pass


def _is_v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == VERSION


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


def _local_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarWorkspaceWslError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarWorkspaceWslError(f"{label} must be a JSON object")
    return value


def _canonical_digest(value: dict[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_exavatar_workspace_wsl(
    *,
    materialization_receipt_path: str | Path,
    strict_preflight_path: str | Path,
    linux_workspace_root: str,
    smplx_gender: str,
    distribution: str = "Ubuntu-22.04",
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    workspace_root = _text(linux_workspace_root, label="Linux workspace root")
    distribution = _text(distribution, label="WSL distribution", maximum=160)
    gender = str(smplx_gender or "").strip().lower()
    if gender not in {"female", "male", "neutral"}:
        raise PhotorealExAvatarWorkspaceWslError("smplx_gender must be explicitly female, male or neutral")
    if not workspace_root.startswith("/") or workspace_root == "/":
        raise PhotorealExAvatarWorkspaceWslError("Linux workspace root must be a non-root absolute Linux path")

    materialization = _local_json(materialization_receipt_path, label="ExAvatar materialization receipt")
    preflight = _local_json(strict_preflight_path, label="ExAvatar strict preflight receipt")
    receipt_path = workspace_root.rstrip("/") + "/workspace-receipt.json"
    receipt = _read_linux_json(
        wsl_exe=wsl_exe,
        distribution=distribution,
        path=receipt_path,
    )
    if receipt.get("format") != FORMAT or not _is_v1(receipt.get("version")):
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt format/version mismatch")
    if receipt.get("smplx_gender") != gender or receipt.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt gender provenance mismatch")
    if receipt.get("dataset") != "Custom" or receipt.get("upstream_default_gender_accepted") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt config authority is invalid")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace disclosed forbidden source/eval data")
    if receipt.get("dependency_root_modified") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace modified pinned dependency root")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace crossed downstream authority")

    declared = str(receipt.get("workspace_sha256") or "").strip().lower()
    if len(declared) != 64 or _canonical_digest(receipt, omit="workspace_sha256") != declared:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace receipt digest mismatch")

    for field in ("performer_id", "selected_epoch_id", "benchmark_plan_sha256", "teacher_input_sha256", "upstream_commit"):
        if receipt.get(field) != materialization.get(field):
            raise PhotorealExAvatarWorkspaceWslError(f"ExAvatar workspace materialization provenance mismatch: {field}")

    expected_materialization_sha = _canonical_digest(materialization)
    if receipt.get("materialization_receipt_sha256") != expected_materialization_sha:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace materialization receipt SHA mismatch")
    if receipt.get("strict_preflight_sha256") != preflight.get("preflight_sha256"):
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace strict preflight SHA mismatch")
    if preflight.get("smplx_gender") != gender or preflight.get("benchmark_environment_ready") is not True:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace strict preflight authority mismatch")
    if preflight.get("blockers") != [] or preflight.get("automatic_restricted_asset_download") is not False:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace strict preflight blockers/asset policy mismatch")

    dataset_relative = str(receipt.get("working_dataset_relative_path") or "").strip().replace("\\", "/")
    if not dataset_relative or dataset_relative.startswith("/") or ".." in dataset_relative.split("/"):
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace dataset relative path is invalid")
    dataset_root = workspace_root.rstrip("/") + "/" + dataset_relative

    _run(
        [wsl_exe, "-d", distribution, "--", "/usr/bin/test", "-d", dataset_root],
        label="verify ExAvatar workspace dataset",
    )
    frames = materialization.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar materialization receipt contains no frames")
    if receipt.get("frame_count") != len(frames):
        raise PhotorealExAvatarWorkspaceWslError("ExAvatar workspace frame count mismatch")
    for raw in frames:
        if not isinstance(raw, dict):
            raise PhotorealExAvatarWorkspaceWslError("ExAvatar materialization frame entry is invalid")
        index = raw.get("exavatar_frame_index")
        expected_sha = str(raw.get("staged_png_sha256") or "").strip().lower()
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or len(expected_sha) != 64:
            raise PhotorealExAvatarWorkspaceWslError("ExAvatar materialization frame provenance is invalid")
        frame_path = f"{dataset_root}/frames/{index}.png"
        completed = _run(
            [wsl_exe, "-d", distribution, "--", "/usr/bin/sha256sum", frame_path],
            label=f"verify ExAvatar workspace frame {index}",
        )
        observed = (completed.stdout or "").strip().split()[0].lower() if completed.stdout else ""
        if observed != expected_sha:
            raise PhotorealExAvatarWorkspaceWslError(f"ExAvatar workspace frame SHA mismatch: {index}")
    return receipt


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
    if receipt.get("format") != FORMAT or not _is_v1(receipt.get("version")):
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
