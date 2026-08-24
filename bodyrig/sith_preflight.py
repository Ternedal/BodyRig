from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence

SITH_REPOSITORY = "SiTH-Diffusion/SiTH"
SITH_REVISION = "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d"
SITH_RUN_SH_BLOB = "e72216b096202f7ac34e0163f215888d01b0fba2"
SITH_REQUIREMENTS_BLOB = "8d6672dc167fd8642583745b910e7ecbf0af641d"
SITH_CENTRALIZE_RGBA_BLOB = "e7976fd53e86463b9e9671848aa9dbe53337e3e0"
SITH_FIT_BLOB = "f5e90e7d82d06bff342335156f23902e6b88e723"
SITH_HALLUCINATE_BLOB = "81ed3064062a47d6205c3e2cffa58dd0db06ee4d"
SITH_RECONSTRUCT_BLOB = "6dff206cf6c487479b528bf91c491e1adef6955b"
SITH_RECON_CONFIG_BLOB = "99df9520c2cb4768f0466282bb2560404fb11d95"
OPENPOSE_REPOSITORY = "CMU-Perceptual-Computing-Lab/openpose"
OPENPOSE_REVISION = "8ca5c1d95a42340b323e9273654d1db98bec779c"
OPENPOSE_CMAKE_BLOB = "2328e66ba9642d324c30bd6fe4d7f9711af7595f"

PINNED_BLOBS = {
    "run.sh": SITH_RUN_SH_BLOB,
    "requirements.txt": SITH_REQUIREMENTS_BLOB,
    "tools/centralize_rgba.py": SITH_CENTRALIZE_RGBA_BLOB,
    "fit.py": SITH_FIT_BLOB,
    "hallucinate.py": SITH_HALLUCINATE_BLOB,
    "reconstruct.py": SITH_RECONSTRUCT_BLOB,
    "recon/config.yaml": SITH_RECON_CONFIG_BLOB,
}

REQUIRED_CHECKPOINTS = (
    "checkpoints/recon_model.pth",
    "checkpoints/save_smplerx.pth",
)
REQUIRED_SMPLX = (
    "data/body_models/smplx/SMPLX_NEUTRAL.pkl",
    "data/body_models/smplx/SMPLX_NEUTRAL.npz",
    "data/body_models/smplx/SMPLX_MALE.pkl",
    "data/body_models/smplx/SMPLX_MALE.npz",
    "data/body_models/smplx/SMPLX_FEMALE.pkl",
    "data/body_models/smplx/SMPLX_FEMALE.npz",
)


class SithPreflightError(RuntimeError):
    pass


def _run_wsl(*, wsl_exe: str, distribution: str, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [wsl_exe, "-d", distribution, "--", *command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        check=False,
    )


def _checked_text(*, wsl_exe: str, distribution: str, command: Sequence[str], label: str) -> str:
    completed = _run_wsl(wsl_exe=wsl_exe, distribution=distribution, command=command)
    if completed.returncode != 0:
        detail = stderr_or_stdout(completed)[-1500:]
        raise SithPreflightError(f"{label} failed: {detail}")
    return completed.stdout.strip()


def stderr_or_stdout(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "").strip()


def _python_probe_script(repo: str, openpose: str) -> str:
    return f'''\
import importlib, json, pathlib, sys
result = {{"python": sys.version.split()[0]}}
modules = (
    ("torch", "torch"),
    ("torchvision", "torchvision"),
    ("kaolin", "kaolin"),
    ("numpy", "numpy"),
    ("cv2", "cv2"),
    ("PIL", "PIL"),
    ("smplx", "smplx"),
    ("diffusers", "diffusers"),
    ("transformers", "transformers"),
    ("trimesh", "trimesh"),
    ("xatlas", "xatlas"),
    ("nvdiffrast.torch", "nvdiffrast"),
)
for module, key in modules:
    try:
        imported = importlib.import_module(module)
        result["import_" + key] = True
        version = getattr(imported, "__version__", None)
        if version is not None:
            result["version_" + key] = str(version)
    except Exception as exc:
        result["import_" + key] = False
        result["error_" + key] = type(exc).__name__ + ": " + str(exc)
try:
    import torch
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_device"] = torch.cuda.get_device_name(0) if result["cuda_available"] else None
except Exception:
    result["cuda_available"] = False
    result["cuda_device"] = None
repo = pathlib.Path({repo!r})
files = {list(REQUIRED_CHECKPOINTS + REQUIRED_SMPLX)!r}
result["files"] = {{name: (repo / name).is_file() for name in files}}
openpose = pathlib.Path({openpose!r})
result["openpose_present"] = openpose.is_file()
print(json.dumps(result, separators=(",", ":")))
'''


def _check_pinned_openpose(*, distribution: str, repo: str, wsl_exe: str, checks: dict[str, Any], errors: list[str]) -> None:
    if not repo.startswith("/"):
        errors.append("OpenPose repository path must be absolute Linux path")
        return
    try:
        head = _checked_text(
            wsl_exe=wsl_exe,
            distribution=distribution,
            command=["git", "-C", repo, "rev-parse", "HEAD"],
            label="OpenPose Git HEAD",
        ).lower()
        checks["openpose_revision"] = head
        if head != OPENPOSE_REVISION:
            errors.append(f"OpenPose revision mismatch: {head}")
    except SithPreflightError as exc:
        errors.append(str(exc))
    try:
        dirty = _checked_text(
            wsl_exe=wsl_exe,
            distribution=distribution,
            command=["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
            label="OpenPose tracked-file status",
        )
        checks["openpose_tracked_clean"] = not bool(dirty)
        if dirty:
            errors.append("OpenPose has modified tracked files")
    except SithPreflightError as exc:
        errors.append(str(exc))
    try:
        actual = _checked_text(
            wsl_exe=wsl_exe,
            distribution=distribution,
            command=["git", "-C", repo, "hash-object", "CMakeLists.txt"],
            label="OpenPose CMakeLists.txt blob",
        ).lower()
        checks["openpose_cmakelists_blob"] = actual
        if actual != OPENPOSE_CMAKE_BLOB:
            errors.append(f"OpenPose CMakeLists.txt blob mismatch: {actual}")
    except SithPreflightError as exc:
        errors.append(str(exc))


def run_preflight(
    *,
    distribution: str,
    repo: str,
    python: str,
    openpose: str,
    openpose_repo: str | None = None,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    for label, value in (("distribution", distribution), ("repo", repo), ("python", python), ("openpose", openpose), ("wsl_exe", wsl_exe)):
        if not isinstance(value, str) or not value.strip():
            raise SithPreflightError(f"SiTH {label} is required")
    if not repo.startswith("/") or not python.startswith("/") or not openpose.startswith("/"):
        raise SithPreflightError("SiTH repo/python/openpose paths must be absolute Linux paths")
    if openpose_repo is not None and (not isinstance(openpose_repo, str) or not openpose_repo.startswith("/")):
        raise SithPreflightError("SiTH openpose_repo must be an absolute Linux path when supplied")

    checks: dict[str, Any] = {
        "format": "bodyrig-sith-preflight",
        "version": 1,
        "repository": SITH_REPOSITORY,
        "expected_revision": SITH_REVISION,
        "distribution": distribution,
        "openpose_repository": OPENPOSE_REPOSITORY,
        "openpose_expected_revision": OPENPOSE_REVISION,
        "openpose_authority_pinned": openpose_repo is not None,
    }
    errors: list[str] = []

    try:
        head = _checked_text(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "rev-parse", "HEAD"], label="SiTH Git HEAD").lower()
        checks["revision"] = head
        if head != SITH_REVISION:
            errors.append(f"SiTH revision mismatch: {head}")
    except SithPreflightError as exc:
        errors.append(str(exc))

    try:
        dirty = _checked_text(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], label="SiTH tracked-file status")
        checks["tracked_clean"] = not bool(dirty)
        if dirty:
            errors.append("SiTH has modified tracked files")
    except SithPreflightError as exc:
        errors.append(str(exc))

    for relative, expected in PINNED_BLOBS.items():
        try:
            actual = _checked_text(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "hash-object", relative], label=f"SiTH {relative} blob").lower()
            checks[f"blob_{relative.replace('/', '_').replace('.', '_')}"] = actual
            if actual != expected:
                errors.append(f"SiTH {relative} blob mismatch: {actual}")
        except SithPreflightError as exc:
            errors.append(str(exc))

    if openpose_repo is not None:
        _check_pinned_openpose(distribution=distribution, repo=openpose_repo, wsl_exe=wsl_exe, checks=checks, errors=errors)

    probe: dict[str, Any] = {}
    completed = _run_wsl(wsl_exe=wsl_exe, distribution=distribution, command=[python, "-c", _python_probe_script(repo, openpose)])
    if completed.returncode != 0:
        errors.append(f"SiTH Python probe failed: {stderr_or_stdout(completed)[-1500:]}")
    else:
        try:
            probe = json.loads(completed.stdout)
        except json.JSONDecodeError:
            errors.append("SiTH Python probe returned invalid JSON")
    checks["environment"] = probe

    for module in ("torch", "torchvision", "kaolin", "numpy", "cv2", "PIL", "smplx", "diffusers", "transformers", "trimesh", "xatlas", "nvdiffrast"):
        if probe.get("import_" + module) is not True:
            errors.append(f"SiTH Python import failed: {module}: {probe.get('error_' + module, 'unknown error')}")
    if probe.get("cuda_available") is not True:
        errors.append("SiTH CUDA is not available")

    expected_versions = {"torch": "2.1.0", "torchvision": "0.16.0", "kaolin": "0.15.0", "numpy": "1.24.1"}
    for name, expected in expected_versions.items():
        actual = str(probe.get("version_" + name, "")).split("+")[0]
        if actual and actual != expected:
            errors.append(f"SiTH {name} version mismatch: expected {expected}, got {actual}")

    files = probe.get("files") if isinstance(probe.get("files"), dict) else {}
    for relative in REQUIRED_CHECKPOINTS + REQUIRED_SMPLX:
        if files.get(relative) is not True:
            errors.append(f"SiTH required asset missing: {relative}")
    if probe.get("openpose_present") is not True:
        errors.append("SiTH OpenPose executable not found")

    checks["ok"] = not errors
    checks["errors"] = errors
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed preflight for the pinned experimental SiTH BodyRig adapter.")
    parser.add_argument("--distribution", required=True, help="WSL distribution name")
    parser.add_argument("--repo", required=True, help="Absolute Linux path to pinned SiTH checkout")
    parser.add_argument("--python", required=True, help="Absolute Linux path to SiTH environment Python")
    parser.add_argument("--openpose", required=True, help="Absolute Linux path to OpenPose executable")
    parser.add_argument("--openpose-repo", help="Optional absolute Linux path to pinned OpenPose v1.7.0 checkout")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--out", help="Optional Windows JSON report path")
    args = parser.parse_args(argv)

    try:
        result = run_preflight(
            distribution=args.distribution,
            repo=args.repo,
            python=args.python,
            openpose=args.openpose,
            openpose_repo=args.openpose_repo,
            wsl_exe=args.wsl_exe,
        )
    except (OSError, SithPreflightError) as exc:
        print(f"BodyRig SiTH preflight: {exc}", file=sys.stderr)
        return 1

    if args.out:
        from pathlib import Path
        output = Path(args.out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            print(f"BodyRig SiTH preflight: output already exists: {output}", file=sys.stderr)
            return 1
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if not result["ok"]:
        for error in result["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    environment = result.get("environment", {})
    print(f"BodyRig SiTH preflight: OK | CUDA: {environment.get('cuda_device', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
