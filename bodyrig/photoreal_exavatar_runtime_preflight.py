from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_exavatar_hand4whole_stage import (
    PhotorealExAvatarHand4WholeStageError,
    validate_hand4whole_assets_receipt,
)

FORMAT = "bodyrig-photoreal-exavatar-runtime-preflight"
VERSION = 1
WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"

EXPECTED_VERSIONS: dict[str, str] = {
    "torch": "2.6.0",
    "torchvision": "0.21.0",
    "numpy": "1.26.4",
    "opencv-python": "4.10.0.84",
    "scipy": "1.15.2",
    "smplx": "0.1.28",
    "lpips": "0.1.4",
    "chumpy": "0.70",
    "mmcv": "2.1.0",
    "mmdet": "3.3.0",
    "mmengine": "0.10.7",
}

REQUIRED_IMPORTS: tuple[str, ...] = (
    "torch",
    "torchvision",
    "numpy",
    "cv2",
    "scipy",
    "smplx",
    "lpips",
    "pytorch3d",
    "mmcv",
    "mmengine",
    "mmdet",
    "chumpy",
    "kornia",
    "yacs",
    "face_alignment",
    "timm",
    "einops",
    "tqdm",
    "PIL",
)

WORKSPACE_IMPORTS: tuple[tuple[str, str], ...] = (
    ("mmpose", "mmpose"),
    ("segment_anything", "segment-anything"),
    ("depth_anything_v2", "Depth-Anything-V2"),
)


class PhotorealExAvatarRuntimePreflightError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarRuntimePreflightError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarRuntimePreflightError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarRuntimePreflightError(f"{label} is invalid")
    return result


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_origin(module: Any) -> str | None:
    path = getattr(module, "__file__", None)
    return None if not path else str(Path(path).resolve())


def build_runtime_preflight(*, workspace_root: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealExAvatarRuntimePreflightError(f"ExAvatar workspace not found: {root}")
    workspace = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if workspace.get("format") != WORKSPACE_FORMAT or workspace.get("version") != VERSION:
        raise PhotorealExAvatarRuntimePreflightError("ExAvatar workspace receipt format/version mismatch")
    if workspace.get("dataset") != "Custom" or workspace.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarRuntimePreflightError("ExAvatar workspace config authority is invalid")
    if workspace.get("held_out_evaluation_disclosed") is not False or workspace.get("production_activation") is not False:
        raise PhotorealExAvatarRuntimePreflightError("ExAvatar workspace crossed source/downstream authority")
    workspace_sha = _sha(workspace.get("workspace_sha256"), label="workspace SHA-256")

    try:
        hand4whole = validate_hand4whole_assets_receipt(workspace_root=root)
    except PhotorealExAvatarHand4WholeStageError as exc:
        raise PhotorealExAvatarRuntimePreflightError(f"Hand4Whole human-model asset gate failed: {exc}") from exc
    if hand4whole.get("workspace_sha256") != workspace_sha:
        raise PhotorealExAvatarRuntimePreflightError("Hand4Whole asset receipt belongs to different workspace")
    hand4whole_sha = _sha(hand4whole.get("hand4whole_assets_sha256"), label="Hand4Whole assets SHA-256")

    repos = root / "repos"
    for module_name, relative_repo in WORKSPACE_IMPORTS:
        repo = repos / relative_repo
        if not repo.is_dir():
            raise PhotorealExAvatarRuntimePreflightError(f"workspace runtime repo missing: {relative_repo}")
        sys.path.insert(0, str(repo))

    blockers: list[str] = []
    import_records: list[dict[str, Any]] = []
    imported: dict[str, Any] = {}
    for name in REQUIRED_IMPORTS:
        try:
            module = importlib.import_module(name)
            imported[name] = module
            import_records.append({"module": name, "available": True, "origin": _module_origin(module), "error": None})
        except Exception as exc:  # dependency imports often raise runtime errors, not ImportError
            blockers.append(f"required import failed: {name}: {type(exc).__name__}: {exc}")
            import_records.append({"module": name, "available": False, "origin": None, "error": f"{type(exc).__name__}: {exc}"})

    workspace_import_records: list[dict[str, Any]] = []
    for module_name, relative_repo in WORKSPACE_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            origin = _module_origin(module)
            repo = (repos / relative_repo).resolve()
            if origin is None or repo not in Path(origin).parents:
                blockers.append(f"workspace import did not resolve from pinned repo: {module_name}")
            workspace_import_records.append({"module": module_name, "available": True, "origin": origin, "expected_repo": str(repo)})
        except Exception as exc:
            blockers.append(f"workspace import failed: {module_name}: {type(exc).__name__}: {exc}")
            workspace_import_records.append({"module": module_name, "available": False, "origin": None, "expected_repo": str((repos / relative_repo).resolve())})

    version_records: list[dict[str, Any]] = []
    for package, expected in EXPECTED_VERSIONS.items():
        observed = _distribution_version(package)
        match = observed == expected
        version_records.append({"package": package, "expected": expected, "observed": observed, "match": match})
        if not match:
            blockers.append(f"package version mismatch: {package}: expected {expected}, observed {observed}")

    cuda_record: dict[str, Any] = {
        "torch_available": "torch" in imported,
        "cuda_available": False,
        "device_count": 0,
        "device_name": None,
        "compute_capability": None,
        "torch_cuda_version": None,
        "smoke_passed": False,
    }
    if "torch" in imported:
        torch = imported["torch"]
        try:
            cuda_record["torch_cuda_version"] = str(torch.version.cuda or "")
            cuda_record["cuda_available"] = bool(torch.cuda.is_available())
            cuda_record["device_count"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
            if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
                blockers.append("PyTorch CUDA is unavailable")
            else:
                cuda_record["device_name"] = str(torch.cuda.get_device_name(0))
                capability = torch.cuda.get_device_capability(0)
                cuda_record["compute_capability"] = [int(capability[0]), int(capability[1])]
                value = (torch.ones((64,), device="cuda:0") * 3.0).sum()
                if float(value.item()) != 192.0:
                    blockers.append("PyTorch CUDA arithmetic smoke returned unexpected result")
                else:
                    cuda_record["smoke_passed"] = True
        except Exception as exc:
            blockers.append(f"PyTorch CUDA smoke failed: {type(exc).__name__}: {exc}")

    pytorch3d_smoke = False
    if "torch" in imported and "pytorch3d" in imported and cuda_record["cuda_available"]:
        try:
            from pytorch3d.transforms import axis_angle_to_matrix

            torch = imported["torch"]
            matrix = axis_angle_to_matrix(torch.zeros((1, 3), device="cuda:0"))
            pytorch3d_smoke = tuple(matrix.shape) == (1, 3, 3)
            if not pytorch3d_smoke:
                blockers.append("PyTorch3D CUDA smoke returned unexpected shape")
        except Exception as exc:
            blockers.append(f"PyTorch3D CUDA smoke failed: {type(exc).__name__}: {exc}")

    gaussian_record: dict[str, Any] = {
        "available": False,
        "origin": None,
        "cuda_extension_available": False,
        "expected_repo": str((repos / "diff-gaussian-rasterization-depth").resolve()),
    }
    gaussian_repo = repos / "diff-gaussian-rasterization-depth"
    sys.path.insert(0, str(gaussian_repo))
    try:
        gaussian = importlib.import_module("diff_gaussian_rasterization_depth")
        origin = _module_origin(gaussian)
        gaussian_record["available"] = True
        gaussian_record["origin"] = origin
        if origin is None or gaussian_repo.resolve() not in Path(origin).parents:
            blockers.append("Gaussian rasterizer import did not resolve from pinned workspace repo")
        extension = importlib.import_module("diff_gaussian_rasterization_depth._C")
        gaussian_record["cuda_extension_available"] = extension is not None
    except Exception as exc:
        blockers.append(f"Gaussian rasterizer CUDA extension import failed: {type(exc).__name__}: {exc}")

    blockers = sorted(set(blockers))
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "workspace_sha256": workspace_sha,
        "hand4whole_assets_sha256": hand4whole_sha,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": ".".join(str(v) for v in sys.version_info[:3]),
        "expected_python_major_minor": "3.10",
        "python_major_minor_match": sys.version_info[:2] == (3, 10),
        "imports": import_records,
        "workspace_imports": workspace_import_records,
        "versions": version_records,
        "cuda": cuda_record,
        "pytorch3d_cuda_smoke_passed": pytorch3d_smoke,
        "gaussian_rasterizer": gaussian_record,
        "runtime_environment_ready": False,
        "blockers": [],
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    if not result["python_major_minor_match"]:
        blockers.append(f"Python version mismatch: expected 3.10, observed {result['python_version']}")
    blockers = sorted(set(blockers))
    result["blockers"] = blockers
    result["runtime_environment_ready"] = not blockers
    result["runtime_preflight_sha256"] = _digest(result, omit="runtime_preflight_sha256")
    return result


def build_runtime_preflight_file(*, workspace_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    result = build_runtime_preflight(workspace_root=workspace_root)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealExAvatarRuntimePreflightError(f"runtime preflight output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
