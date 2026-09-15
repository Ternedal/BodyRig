from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-exavatar-runtime-setup"
VERSION = 1
PYTORCH3D_COMMIT = "0a7d4c1a171e8b768c63f15b17564f9ad495f49b"
CHUMPY_PATCH = "bodyrig-chumpy-0.70-numpy-alias-v1"
TORCHGEOMETRY_PATCH = "hand4whole-author-float-mask-v1"
EXPECTED_REQUESTED_VERSIONS: dict[str, str] = {
    "torch": "2.6.0",
    "torchvision": "0.21.0",
    "numpy": "1.26.4",
    "scipy": "1.15.2",
    "opencv_python": "4.10.0.84",
    "smplx": "0.1.28",
    "lpips": "0.1.4",
    "chumpy": "0.70",
    "mmcv": "2.1.0",
    "mmengine": "0.10.7",
    "mmdet": "3.3.0",
    "mmpose": "1.3.2",
}


class PhotorealExAvatarRuntimeSetupReceiptError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} is invalid")
    return result


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _patch(value: Any, *, label: str, expected_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} receipt is invalid")
    if value.get("patch") != expected_name:
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} patch identity mismatch")
    path = str(value.get("path") or "").strip()
    if not path.startswith("/"):
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} patch path is not absolute")
    _sha(value.get("sha256"), label=f"{label} patched SHA-256")
    return dict(value)


def validate_runtime_setup_receipt(*, linux_python: str | Path) -> dict[str, Any]:
    # Preserve the venv entry path instead of Path.resolve(): bin/python is
    # normally a symlink to /usr/bin/python3.10, and resolving it would lose
    # the venv root that owns the setup receipt.
    python = Path(os.path.abspath(os.fspath(Path(linux_python).expanduser())))
    if not python.is_absolute() or python.name != "python" or python.parent.name != "bin":
        raise PhotorealExAvatarRuntimeSetupReceiptError("ExAvatar Python path is not a canonical venv bin/python")
    root = python.parent.parent
    path = root / "bodyrig-exavatar-runtime-setup.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"runtime setup receipt is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup receipt must be a JSON object")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup receipt format/version mismatch")
    if str(value.get("linux_python") or "") != str(python):
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup receipt targets different Python executable")
    if value.get("pytorch3d_commit") != PYTORCH3D_COMMIT:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup PyTorch3D commit mismatch")
    requested = value.get("requested_versions")
    if not isinstance(requested, Mapping) or dict(requested) != EXPECTED_REQUESTED_VERSIONS:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup requested-version set mismatch")
    chumpy_patch = _patch(value.get("chumpy_patch"), label="Chumpy", expected_name=CHUMPY_PATCH)
    torchgeometry_patch = _patch(value.get("torchgeometry_patch"), label="torchgeometry", expected_name=TORCHGEOMETRY_PATCH)
    observed = value.get("observed")
    if not isinstance(observed, Mapping):
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup observed probe is invalid")
    if observed.get("cuda_smoke") is not True or observed.get("chumpy_smoke") is not True or observed.get("torchgeometry_smoke") is not True:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup smoke evidence is incomplete")
    if str(observed.get("chumpy") or "") != "0.70":
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup observed Chumpy version mismatch")
    nvcc = value.get("nvcc")
    nvidia = value.get("nvidia_smi")
    if not isinstance(nvcc, list) or not nvcc or not isinstance(nvidia, list) or not nvidia:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup CUDA/GPU provenance is missing")
    if value.get("photoreal_acceptance_authority") is not False or value.get("build_only") is not True:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup crossed photoreal/build authority")
    if value.get("production_activation") is not False:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup crossed production authority")
    declared = _sha(value.get("setup_sha256"), label="runtime setup SHA-256")
    if _digest(value, omit="setup_sha256") != declared:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup receipt digest mismatch")
    result = dict(value)
    result["chumpy_patch"] = chumpy_patch
    result["torchgeometry_patch"] = torchgeometry_patch
    return result
