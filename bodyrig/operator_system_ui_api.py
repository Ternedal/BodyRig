from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter


router = APIRouter()

_DISTRIBUTION = "Ubuntu-22.04"
_EXAVATAR_PYTHON = "/opt/bodyrig-exavatar/bin/python"
_MATERIALIZER_PYTHON = "/opt/bodyrig-photoreal/bin/python"
_PUBLIC_DEPENDENCY_RECEIPT = "/opt/bodyrig-exavatar/deps/bodyrig-public-dependencies.json"


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
    materializer_runtime = test("-x", _MATERIALIZER_PYTHON)
    public_dependencies = test("-f", _PUBLIC_DEPENDENCY_RECEIPT)
    gpu_ready = gpu_code == 0 and bool(gpu_text)
    cuda_ready = nvcc_code == 0 and cuda_version == "12.4"
    return {
        "ready": all(
            (
                gpu_ready,
                cuda_ready,
                exavatar_runtime,
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
        "materializer_runtime": materializer_runtime,
        "public_dependencies": public_dependencies,
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


@router.get("/api/v1/operator/system-readiness")
def operator_system_readiness() -> dict:
    return {
        "read_only": True,
        "windows": os.name == "nt",
        "powershell_7": bool(shutil.which("pwsh.exe") or shutil.which("pwsh")),
        "wsl_cuda": _wsl_status(),
        "quest": _quest_status(),
        "production_activation": False,
    }
