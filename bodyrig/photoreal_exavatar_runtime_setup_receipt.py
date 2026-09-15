from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-exavatar-runtime-setup"
VERSION = 1
EXPECTED_CUDA_VERSION = "12.4"
PYTORCH3D_COMMIT = "0a7d4c1a171e8b768c63f15b17564f9ad495f49b"
PYTORCH3D_REPOSITORY = "https://github.com/facebookresearch/pytorch3d.git"
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
OBSERVED_VERSION_KEYS: dict[str, str] = {
    "torch": "torch",
    "torchvision": "torchvision",
    "numpy": "numpy",
    "scipy": "scipy",
    "opencv_python": "opencv",
    "smplx": "smplx",
    "lpips": "lpips",
    "chumpy": "chumpy",
    "mmcv": "mmcv",
    "mmengine": "mmengine",
    "mmdet": "mmdet",
    "mmpose": "mmpose",
}


class PhotorealExAvatarRuntimeSetupReceiptError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _version_matches(actual: str, expected: str) -> bool:
    # PyTorch CUDA wheels legitimately expose a PEP 440 local suffix such as
    # 2.6.0+cu124. Pin the public/base version here; CUDA parity is verified
    # separately and exactly through torch.version.cuda + nvcc evidence.
    return actual == expected or actual.split("+", 1)[0] == expected


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


def _verify_live_patch(record: Mapping[str, Any], *, root: Path, label: str) -> Path:
    path = Path(str(record.get("path") or "")).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} patched file is missing: {path}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} patched file is outside ExAvatar venv: {resolved}") from exc
    if not resolved.is_file():
        raise PhotorealExAvatarRuntimeSetupReceiptError(f"{label} patched path is not a file: {resolved}")
    expected = _sha(record.get("sha256"), label=f"{label} patched SHA-256")
    observed = _file_sha(resolved)
    if observed != expected:
        raise PhotorealExAvatarRuntimeSetupReceiptError(
            f"{label} patched bytes changed after setup: expected {expected}, observed {observed}"
        )
    return resolved


def _installed_pytorch3d_provenance() -> dict[str, str]:
    try:
        distribution = importlib.metadata.distribution("pytorch3d")
    except importlib.metadata.PackageNotFoundError as exc:
        raise PhotorealExAvatarRuntimeSetupReceiptError("installed PyTorch3D distribution is missing") from exc
    raw = distribution.read_text("direct_url.json")
    if not raw:
        raise PhotorealExAvatarRuntimeSetupReceiptError("installed PyTorch3D direct_url.json is missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PhotorealExAvatarRuntimeSetupReceiptError("installed PyTorch3D direct_url.json is invalid") from exc
    if not isinstance(value, Mapping):
        raise PhotorealExAvatarRuntimeSetupReceiptError("installed PyTorch3D direct URL provenance is invalid")
    url = str(value.get("url") or "").rstrip("/")
    expected_url = PYTORCH3D_REPOSITORY.rstrip("/")
    if url != expected_url:
        raise PhotorealExAvatarRuntimeSetupReceiptError(
            f"installed PyTorch3D source URL mismatch: expected {expected_url}, observed {url or '<missing>'}"
        )
    vcs = value.get("vcs_info")
    if not isinstance(vcs, Mapping) or vcs.get("vcs") != "git":
        raise PhotorealExAvatarRuntimeSetupReceiptError("installed PyTorch3D VCS provenance is missing")
    commit = str(vcs.get("commit_id") or "").strip().lower()
    if commit != PYTORCH3D_COMMIT:
        raise PhotorealExAvatarRuntimeSetupReceiptError(
            f"installed PyTorch3D commit mismatch: expected {PYTORCH3D_COMMIT}, observed {commit or '<missing>'}"
        )
    return {"url": url, "commit": commit}


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
    if str(value.get("expected_cuda_version") or "") != EXPECTED_CUDA_VERSION:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup expected CUDA version mismatch")
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
    if str(observed.get("torch_cuda") or "") != EXPECTED_CUDA_VERSION:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup observed Torch CUDA version mismatch")
    for requested_key, observed_key in OBSERVED_VERSION_KEYS.items():
        expected = EXPECTED_REQUESTED_VERSIONS[requested_key]
        actual = str(observed.get(observed_key) or "")
        if not _version_matches(actual, expected):
            raise PhotorealExAvatarRuntimeSetupReceiptError(
                f"runtime setup observed version mismatch for {requested_key}: expected {expected}, observed {actual or '<missing>'}"
            )

    nvcc = value.get("nvcc")
    nvidia = value.get("nvidia_smi")
    if not isinstance(nvcc, list) or not nvcc or not isinstance(nvidia, list) or not nvidia:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup CUDA/GPU provenance is missing")
    if f"release {EXPECTED_CUDA_VERSION}" not in "\n".join(str(line) for line in nvcc):
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup nvcc/Torch CUDA parity evidence is missing")
    if value.get("photoreal_acceptance_authority") is not False or value.get("build_only") is not True:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup crossed photoreal/build authority")
    if value.get("production_activation") is not False:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup crossed production authority")

    declared = _sha(value.get("setup_sha256"), label="runtime setup SHA-256")
    if _digest(value, omit="setup_sha256") != declared:
        raise PhotorealExAvatarRuntimeSetupReceiptError("runtime setup receipt digest mismatch")

    # A valid historic receipt is not enough. Re-hash the exact patched files
    # and verify PEP 610 provenance for the live PyTorch3D installation so a
    # later pip install/manual edit cannot masquerade as the pinned runtime.
    chumpy_live_path = _verify_live_patch(chumpy_patch, root=root, label="Chumpy")
    torchgeometry_live_path = _verify_live_patch(torchgeometry_patch, root=root, label="torchgeometry")
    pytorch3d = _installed_pytorch3d_provenance()

    result = dict(value)
    result["chumpy_patch"] = chumpy_patch
    result["torchgeometry_patch"] = torchgeometry_patch
    result["live_patch_bytes_verified"] = True
    result["chumpy_live_path"] = str(chumpy_live_path)
    result["torchgeometry_live_path"] = str(torchgeometry_live_path)
    result["pytorch3d_live_provenance"] = pytorch3d
    return result
