from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .operator_launch import OperatorLaunchError, launch_canonical_operator
from .storage import data_dir
from .ui_jobs import operator_checkout_status


router = APIRouter()

_DISTRIBUTION = "Ubuntu-22.04"
_EXAVATAR_PYTHON = "/opt/bodyrig-exavatar/bin/python"
_MATERIALIZER_PYTHON = "/opt/bodyrig-photoreal/bin/python"
_PUBLIC_DEPENDENCY_RECEIPT = "/opt/bodyrig-exavatar/deps/bodyrig-public-dependencies.json"
_EXAVATAR_RUNTIME_MARKER = "/opt/bodyrig-exavatar/pyvenv.cfg"
_EXAVATAR_RUNTIME_RECEIPT = "/opt/bodyrig-exavatar/bodyrig-exavatar-runtime-setup.json"
_EXAVATAR_PROCESS_MARKERS = (
    "photoreal_exavatar_preprocess_cli",
    "run_colmap.py",
    "run_mmpose.py",
    "run_deca.py",
    "run_hand4whole.py",
    "fit.py",
    "unwrap.py",
    "smooth_smplx_params.py",
    "run_sam.py",
    "run_depth_anything.py",
    "train.py",
    "get_neutral_pose.py",
)


class OperatorSystemActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "run-rig-preflight",
        "run-rig-preflight-quest",
        "run-exavatar-readiness-doctor",
        "setup-exavatar-public-code",
        "setup-exavatar-runtime",
        "resume-exavatar-runtime",
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(argv: list[str], *, timeout: float = 5.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    text = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, text


def _wsl_status() -> dict[str, Any]:
    wsl = shutil.which("wsl.exe") or "wsl.exe"
    code, detail = _run([wsl, "-d", _DISTRIBUTION, "--", "/usr/bin/env", "true"])
    if code != 0:
        return {
            "available": False,
            "ready": False,
            "distribution": _DISTRIBUTION,
            "reason": detail or "WSL distribution is not callable",
            "gpu": None,
            "cuda": None,
            "exavatar_runtime": False,
            "materializer_runtime": False,
            "public_dependencies": False,
        }

    gpu_code, gpu_text = _run(
        [
            wsl,
            "-d",
            _DISTRIBUTION,
            "--",
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    nvcc_code, nvcc_text = _run([wsl, "-d", _DISTRIBUTION, "--", "nvcc", "--version"])
    match = re.search(r"release\s+([0-9]+\.[0-9]+)", nvcc_text)
    cuda_version = match.group(1) if match else None

    def test(kind: str, path: str) -> bool:
        test_code, _ = _run([wsl, "-d", _DISTRIBUTION, "--", "/usr/bin/test", kind, path])
        return test_code == 0

    exavatar_runtime = test("-x", _EXAVATAR_PYTHON)
    runtime_marker = test("-f", _EXAVATAR_RUNTIME_MARKER)
    runtime_receipt = test("-f", _EXAVATAR_RUNTIME_RECEIPT)
    materializer_runtime = test("-x", _MATERIALIZER_PYTHON)
    public_dependencies = test("-f", _PUBLIC_DEPENDENCY_RECEIPT)

    ps_code, ps_text = _run(
        [wsl, "-d", _DISTRIBUTION, "--", "/usr/bin/ps", "-eo", "pid=,args="],
        timeout=3.0,
    )
    active_exavatar_processes: list[str] = []
    if ps_code == 0:
        for line in ps_text.splitlines():
            text_line = line.strip()
            if text_line and any(marker in text_line for marker in _EXAVATAR_PROCESS_MARKERS):
                active_exavatar_processes.append(text_line[:1200])

    gpu_ready = gpu_code == 0 and bool(gpu_text)
    cuda_ready = nvcc_code == 0 and cuda_version == "12.4"
    runtime_complete = exavatar_runtime and runtime_receipt
    return {
        "available": True,
        "ready": all(
            (
                gpu_ready,
                cuda_ready,
                runtime_complete,
                materializer_runtime,
                public_dependencies,
            )
        ),
        "distribution": _DISTRIBUTION,
        "reason": None,
        "gpu": {
            "ready": gpu_ready,
            "summary": gpu_text or None,
        },
        "cuda": {
            "ready": cuda_ready,
            "version": cuda_version,
            "required_version": "12.4",
        },
        "exavatar_runtime": exavatar_runtime,
        "exavatar_runtime_marker": runtime_marker,
        "exavatar_runtime_receipt": runtime_receipt,
        "exavatar_runtime_complete": runtime_complete,
        "materializer_runtime": materializer_runtime,
        "public_dependencies": public_dependencies,
        "active_exavatar_processes": active_exavatar_processes[:20],
        "busy": bool(active_exavatar_processes),
    }


def _renderer_contract() -> dict[str, Any] | None:
    path = _repo_root() / "reference-renderer" / "renderer-contract.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _quest_status() -> dict[str, Any]:
    contract = _renderer_contract()
    if contract is None:
        return {
            "ready": False,
            "reason": "Reference renderer contract is unreadable",
            "unity_version": None,
            "adb_path": None,
            "devices": [],
        }
    unity_version = str(contract.get("unity_editor_version") or "").strip()
    if not unity_version:
        return {
            "ready": False,
            "reason": "Renderer contract has no pinned Unity version",
            "unity_version": None,
            "adb_path": None,
            "devices": [],
        }
    unity = Path(
        rf"C:\Program Files\Unity\Hub\Editor\{unity_version}\Editor\Unity.exe"
    )
    adb = (
        unity.parent
        / "Data"
        / "PlaybackEngines"
        / "AndroidPlayer"
        / "SDK"
        / "platform-tools"
        / "adb.exe"
    )
    if os.name != "nt":
        return {
            "ready": False,
            "reason": "Quest/Unity physical probe is Windows-only",
            "unity_version": unity_version,
            "unity_present": False,
            "adb_path": str(adb),
            "adb_present": False,
            "devices": [],
        }
    if not unity.is_file() or not adb.is_file():
        return {
            "ready": False,
            "reason": "Pinned Unity editor or Android adb is missing",
            "unity_version": unity_version,
            "unity_present": unity.is_file(),
            "adb_path": str(adb),
            "adb_present": adb.is_file(),
            "devices": [],
        }

    code, output = _run([str(adb), "devices"], timeout=4.0)
    if code != 0:
        return {
            "ready": False,
            "reason": output or "Pinned adb devices failed",
            "unity_version": unity_version,
            "unity_present": True,
            "adb_path": str(adb),
            "adb_present": True,
            "devices": [],
        }

    devices: list[dict[str, Any]] = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 2 or parts[1] != "device":
            continue
        serial = parts[0]
        model_code, model = _run(
            [str(adb), "-s", serial, "shell", "getprop", "ro.product.model"],
            timeout=3.0,
        )
        model = model.strip() if model_code == 0 else ""
        devices.append(
            {
                "serial": serial,
                "model": model or None,
                "quest_class": bool(re.search(r"(?i)(quest|oculus)", model)),
            }
        )
    quest = [item for item in devices if item["quest_class"]]
    return {
        "ready": len(quest) >= 1,
        "reason": None if quest else "No online Quest/Oculus adb device",
        "unity_version": unity_version,
        "unity_present": True,
        "adb_path": str(adb),
        "adb_present": True,
        "devices": devices,
        "quest_device_count": len(quest),
    }


def _action_catalog(wsl_status: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "id": "run-rig-preflight",
            "label": "Kør rig-preflight",
            "mutates_environment": False,
            "requires_quest": False,
        },
        {
            "id": "run-rig-preflight-quest",
            "label": "Kør Quest-preflight",
            "mutates_environment": False,
            "requires_quest": True,
        },
        {
            "id": "run-exavatar-readiness-doctor",
            "label": "Kør ExAvatar readiness",
            "mutates_environment": False,
            "requires_quest": False,
        },
    ]
    if wsl_status.get("busy") is True or wsl_status.get("available") is not True:
        return actions
    if wsl_status.get("public_dependencies") is not True:
        actions.append(
            {
                "id": "setup-exavatar-public-code",
                "label": "Installér pinned ExAvatar-kode",
                "mutates_environment": True,
                "requires_quest": False,
            }
        )
    gpu_ready = isinstance(wsl_status.get("gpu"), dict) and wsl_status["gpu"].get("ready") is True
    cuda_ready = isinstance(wsl_status.get("cuda"), dict) and wsl_status["cuda"].get("ready") is True
    if (
        gpu_ready
        and cuda_ready
        and wsl_status.get("exavatar_runtime_complete") is not True
    ):
        partial = (
            wsl_status.get("exavatar_runtime_marker") is True
            or wsl_status.get("exavatar_runtime") is True
        )
        actions.append(
            {
                "id": "resume-exavatar-runtime" if partial else "setup-exavatar-runtime",
                "label": "Genoptag ExAvatar-runtime" if partial else "Installér ExAvatar-runtime",
                "mutates_environment": True,
                "requires_quest": False,
            }
        )
    return actions


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _canonical_system_command(action: str, root: Path) -> str:
    if action in {"run-rig-preflight", "run-rig-preflight-quest"}:
        script = root / "high-fidelity-rig-preflight.ps1"
        if not script.is_file():
            raise HTTPException(
                status_code=409,
                detail=f"Canonical rig preflight mangler: {script}",
            )
        command = f"& {_ps_quote(script)}"
        if action == "run-rig-preflight-quest":
            command += " -RequireQuestConnected"
        return command
    if action == "run-exavatar-readiness-doctor":
        script = root / "check-photoreal-v2-exavatar-readiness.ps1"
        if not script.is_file():
            raise HTTPException(status_code=409, detail=f"ExAvatar readiness doctor mangler: {script}")
        return f"& {_ps_quote(script)}"
    if action == "setup-exavatar-public-code":
        script = root / "setup-photoreal-exavatar-public-code.ps1"
        if not script.is_file():
            raise HTTPException(status_code=409, detail=f"ExAvatar public-code setup mangler: {script}")
        return f"& {_ps_quote(script)}"
    if action in {"setup-exavatar-runtime", "resume-exavatar-runtime"}:
        script = root / "setup-photoreal-exavatar-wsl.ps1"
        if not script.is_file():
            raise HTTPException(status_code=409, detail=f"ExAvatar runtime setup mangler: {script}")
        command = f"& {_ps_quote(script)}"
        if action == "resume-exavatar-runtime":
            command += " -Resume"
        return command
    raise HTTPException(status_code=422, detail="Ukendt canonical systemhandling.")


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        code, output = _run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            timeout=2.0,
        )
        if code != 0:
            return False
        lowered = output.lower()
        return bool(output) and "no tasks are running" not in lowered and f'"{pid}"' in output
    return Path(f"/proc/{pid}").exists()


def _operator_launch_result(
    receipt_path: Path,
    *,
    launch_id: str,
    pid: int,
    request_sha256: str | None = None,
) -> dict[str, Any] | None:
    result_path = receipt_path.parent / "result.json"
    if not result_path.is_file() or result_path.is_symlink():
        return None
    try:
        value = json.loads(result_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("format") != "bodyrig-operator-launch-result":
        return None
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        return None
    if str(value.get("launch_id") or "") != launch_id:
        return None
    result_pid_raw = value.get("pid")
    exit_code_raw = value.get("exit_code")
    duration_raw = value.get("duration_seconds")
    if (
        isinstance(result_pid_raw, bool)
        or not isinstance(result_pid_raw, int)
        or isinstance(exit_code_raw, bool)
        or not isinstance(exit_code_raw, int)
        or isinstance(duration_raw, bool)
        or not isinstance(duration_raw, (int, float))
    ):
        return None
    result_pid = result_pid_raw
    exit_code = exit_code_raw
    duration = float(duration_raw)
    if result_pid != pid or duration < 0:
        return None
    state = str(value.get("state") or "")
    if state not in {"succeeded", "failed"}:
        return None
    if (exit_code == 0) != (state == "succeeded"):
        return None
    finished = str(value.get("finished_utc") or "").strip()
    if not finished:
        return None
    expected_request_sha256 = str(request_sha256 or "").strip().lower()
    if expected_request_sha256:
        actual_request_sha256 = str(value.get("request_sha256") or "").strip().lower()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_request_sha256)
            or actual_request_sha256 != expected_request_sha256
        ):
            return None
    child_pid_raw = value.get("child_pid")
    child_pid = None
    if child_pid_raw is not None:
        if isinstance(child_pid_raw, bool) or not isinstance(child_pid_raw, int) or child_pid_raw <= 0:
            return None
        child_pid = child_pid_raw
    return {
        "state": state,
        "exit_code": exit_code,
        "finished_utc": finished,
        "duration_seconds": duration,
        "child_pid": child_pid,
    }


def _operator_launches(limit: int = 12) -> list[dict[str, Any]]:
    root = data_dir() / "operator-launches"
    if not root.is_dir() or root.is_symlink():
        return []
    values: list[dict[str, Any]] = []
    for receipt_path in root.glob("*/*/launch.json"):
        if not receipt_path.is_file() or receipt_path.is_symlink():
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        launch_id = str(receipt.get("launch_id") or "").strip()
        category = str(receipt.get("category") or "").strip()
        started = str(receipt.get("started_utc") or "").strip()
        process_role = str(receipt.get("process_role") or "").strip()
        request_sha256 = str(receipt.get("request_sha256") or "").strip().lower()
        try:
            pid = int(receipt.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        log_path = receipt_path.parent / "operator.log"
        log_tail = ""
        log_bytes = 0
        log_modified = None
        if log_path.is_file() and not log_path.is_symlink():
            try:
                stat = log_path.stat()
                log_bytes = stat.st_size
                log_modified = stat.st_mtime
                raw = log_path.read_text(encoding="utf-8", errors="replace")
                log_tail = "\n".join(raw.splitlines()[-24:])[-8000:]
            except OSError:
                pass
        terminal = _operator_launch_result(
            receipt_path,
            launch_id=launch_id,
            pid=pid,
            request_sha256=request_sha256 or None,
        )
        running = False if terminal is not None else _pid_running(pid)
        state = terminal["state"] if terminal is not None else ("running" if running else "unknown")
        values.append(
            {
                "launch_id": launch_id,
                "category": category,
                "pid": pid or None,
                "process_role": process_role or None,
                "child_pid": terminal.get("child_pid") if terminal is not None else None,
                "running": running,
                "state": state,
                "exit_code": terminal.get("exit_code") if terminal is not None else None,
                "finished_utc": terminal.get("finished_utc") if terminal is not None else None,
                "duration_seconds": terminal.get("duration_seconds") if terminal is not None else None,
                "result_recorded": terminal is not None,
                "started_utc": started or None,
                "context": receipt.get("context") if isinstance(receipt.get("context"), dict) else {},
                "log_bytes": log_bytes,
                "log_modified_unix": log_modified,
                "log_tail": log_tail,
            }
        )
    values.sort(key=lambda item: str(item.get("started_utc") or ""), reverse=True)
    return values[: max(1, min(int(limit), 50))]


@router.get("/api/v1/operator/launches")
def operator_launches(limit: int = 12) -> dict:
    return {
        "launches": _operator_launches(limit),
        "read_only": True,
        "production_activation": False,
    }


@router.get("/api/v1/operator/system-readiness")
def operator_system_readiness() -> dict:
    wsl_status = _wsl_status()
    return {
        "read_only": True,
        "windows": os.name == "nt",
        "powershell_7": bool(shutil.which("pwsh.exe") or shutil.which("pwsh")),
        "wsl_cuda": wsl_status,
        "quest": _quest_status(),
        "actions": _action_catalog(wsl_status),
        "production_activation": False,
    }


@router.post("/api/v1/operator/system-readiness/action")
def operator_system_readiness_action(request: OperatorSystemActionRequest) -> dict:
    authority = operator_checkout_status()
    if authority.get("ok") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(authority.get("reason") or "Operator checkout is not authoritative."),
        )
    root_value = str(authority.get("root") or "").strip()
    root = Path(root_value).expanduser().resolve() if root_value else _repo_root()
    if root != _repo_root():
        raise HTTPException(
            status_code=409,
            detail="Operator authority root differs from the running BodyRig checkout.",
        )
    wsl_status = _wsl_status()
    allowed = {item["id"] for item in _action_catalog(wsl_status)}
    if request.action not in allowed:
        if wsl_status.get("busy") is True:
            raise HTTPException(
                status_code=409,
                detail="ExAvatar er aktiv; miljøændrende setup er låst indtil processen er færdig.",
            )
        raise HTTPException(
            status_code=409,
            detail="Den canonicale systemhandling er ikke relevant for den aktuelle readiness-state.",
        )
    command = _canonical_system_command(request.action, root)
    try:
        launch = launch_canonical_operator(
            command,
            category="system-preflight",
            context={
                "action": request.action,
                "bodyrig_revision": str(authority.get("revision") or ""),
            },
            cwd=root,
        )
    except OperatorLaunchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "launched": True,
        "launch": launch,
        "action": request.action,
        "production_activation": False,
    }
