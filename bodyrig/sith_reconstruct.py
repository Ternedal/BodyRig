from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .sith_model import SithModelError, digest_model_tree
from .sith_preflight import PINNED_BLOBS, SITH_CENTRALIZE_RGBA_BLOB, SITH_REVISION
from .sith_prepare import SithPrepareError, load_stage, validate_openpose_result

FORMAT = "bodyrig-sith-reconstruction"
VERSION = 1
DEFAULT_SEED = 1337
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FIT_PARAM_LENGTHS = {
    "global_orient": 3,
    "body_pose": 63,
    "betas": 10,
    "left_hand_pose": 45,
    "right_hand_pose": 45,
    "jaw_pose": 3,
    "expression": 10,
    "leye_pose": 3,
    "reye_pose": 3,
    "transl": 3,
    "scale": 1,
}


class SithReconstructError(RuntimeError):
    pass


def _run_wsl(*, wsl_exe: str, distribution: str, command: Sequence[str], cwd: str | None = None, timeout: int = 86_400) -> subprocess.CompletedProcess[str]:
    invocation = [wsl_exe, "-d", distribution]
    if cwd is not None:
        invocation.extend(("--cd", cwd))
    invocation.extend(("--", *command))
    return subprocess.run(invocation, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False, check=False, timeout=timeout)


def _checked_wsl(*, wsl_exe: str, distribution: str, command: Sequence[str], label: str, cwd: str | None = None, timeout: int = 86_400) -> str:
    try:
        completed = _run_wsl(wsl_exe=wsl_exe, distribution=distribution, command=command, cwd=cwd, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SithReconstructError(f"{label} could not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-3000:]
        raise SithReconstructError(f"{label} failed with exit code {completed.returncode}: {detail}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _png_size(path: Path, *, label: str) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise SithReconstructError(f"{label} is not a canonical PNG")
    width, height = struct.unpack(">II", header[16:24])
    if not 1 <= width <= 16384 or not 1 <= height <= 16384:
        raise SithReconstructError(f"{label} dimensions are invalid")
    return width, height


def _read_json(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise SithReconstructError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithReconstructError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithReconstructError(f"{label} must be an object")
    return raw, value


def _linux_path(path: Path, *, wsl_exe: str, distribution: str) -> str:
    value = _checked_wsl(wsl_exe=wsl_exe, distribution=distribution, command=["wslpath", "-a", str(path)], label="WSL path translation", timeout=30).strip()
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise SithReconstructError("wslpath returned an invalid absolute Linux path")
    return value


def verify_execution_authority(*, distribution: str, repo: str, wsl_exe: str) -> None:
    if not repo.startswith("/"):
        raise SithReconstructError("SiTH repo must be an absolute Linux path")
    head = _checked_wsl(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "rev-parse", "HEAD"], label="SiTH Git HEAD", timeout=30).lower()
    if head != SITH_REVISION:
        raise SithReconstructError(f"SiTH revision mismatch: {head or 'unknown'}")
    dirty = _checked_wsl(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], label="SiTH tracked-file status", timeout=30)
    if dirty.strip():
        raise SithReconstructError("SiTH checkout has modified tracked files")
    for relative, expected in PINNED_BLOBS.items():
        actual = _checked_wsl(wsl_exe=wsl_exe, distribution=distribution, command=["git", "-C", repo, "hash-object", relative], label=f"SiTH {relative} blob", timeout=30).lower()
        if actual != expected:
            raise SithReconstructError(f"SiTH {relative} blob mismatch: {actual}")


def load_prepared_input(workspace: str | Path) -> tuple[Path, dict[str, Any], str]:
    try:
        stage, stage_manifest, stage_sha = load_stage(workspace)
    except SithPrepareError as exc:
        raise SithReconstructError(str(exc)) from exc
    prep_raw, prep = _read_json(stage / "prep.json", label="SiTH prepared-input evidence")
    required = {"format", "version", "stage_manifest_sha256", "subject_track_id", "sith_revision", "centralizer_blob", "centralized_image_sha256", "openpose_keypoints_sha256", "centralized_size", "openpose_quality"}
    if set(prep) != required:
        raise SithReconstructError("SiTH prepared-input fields must match v1 exactly")
    if prep["format"] != "bodyrig-sith-prepared-input" or prep["version"] != 1:
        raise SithReconstructError("unsupported SiTH prepared-input format/version")
    if prep["stage_manifest_sha256"] != stage_sha:
        raise SithReconstructError("SiTH prepared input is not bound to current stage manifest")
    if prep["subject_track_id"] != stage_manifest["subject_track_id"]:
        raise SithReconstructError("SiTH prepared input subject track mismatch")
    if prep["sith_revision"] != SITH_REVISION or prep["centralizer_blob"] != SITH_CENTRALIZE_RGBA_BLOB:
        raise SithReconstructError("SiTH prepared input authority mismatch")
    if prep["centralized_size"] != [1024, 1024]:
        raise SithReconstructError("SiTH prepared input size mismatch")
    for field in ("centralized_image_sha256", "openpose_keypoints_sha256"):
        if not isinstance(prep[field], str) or not SHA_RE.fullmatch(prep[field]):
            raise SithReconstructError(f"SiTH prepared input {field} is invalid")
    image = stage / "images" / "000.png"
    keypoints = stage / "images" / "000_keypoints.json"
    if not image.is_file() or _sha256(image) != prep["centralized_image_sha256"]:
        raise SithReconstructError("SiTH centralized image byte hash mismatch")
    if _png_size(image, label="SiTH centralized image") != (1024, 1024):
        raise SithReconstructError("SiTH centralized image size mismatch")
    if not keypoints.is_file() or _sha256(keypoints) != prep["openpose_keypoints_sha256"]:
        raise SithReconstructError("SiTH OpenPose keypoint byte hash mismatch")
    try:
        actual_quality = validate_openpose_result(keypoints)
    except SithPrepareError as exc:
        raise SithReconstructError(str(exc)) from exc
    if prep["openpose_quality"] != actual_quality:
        raise SithReconstructError("SiTH OpenPose quality evidence mismatch")
    return stage, prep, hashlib.sha256(prep_raw).hexdigest()


def _require_empty(path: Path, *, label: str) -> None:
    if not path.is_dir() or any(path.iterdir()):
        raise SithReconstructError(f"{label} must exist and be empty before reconstruction")


def _finite_vector(value: Any, *, field: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise SithReconstructError(f"SiTH fit {field} must contain exactly {length} values")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise SithReconstructError(f"SiTH fit {field} contains a non-finite number")
        result.append(float(item))
    return result


def validate_fit_params(path: str | Path) -> dict[str, list[float]]:
    _, params = _read_json(Path(path).expanduser().resolve(), label="SiTH fit parameter JSON")
    if set(params) != set(FIT_PARAM_LENGTHS):
        raise SithReconstructError("SiTH fit parameter fields must match the pinned fit.py debug contract")
    normalized = {field: _finite_vector(params[field], field=field, length=length) for field, length in FIT_PARAM_LENGTHS.items()}
    if not 0.05 <= normalized["scale"][0] <= 20.0:
        raise SithReconstructError("SiTH fit scale is outside the accepted range")
    return normalized


def _safe_texture_name(value: str) -> str:
    value = value.strip().strip('"')
    if not value or Path(value).name != value or value in {".", ".."} or "/" in value or "\\" in value:
        raise SithReconstructError("SiTH MTL texture reference must be a leaf filename")
    return value


def validate_reconstruction_outputs(stage: Path) -> dict[str, str]:
    smplx_obj = stage / "smplx" / "000_smplx.obj"
    fit_params = stage / "smplx" / "000_fit.json"
    back = stage / "back_images" / "000_000.png"
    meshes = stage / "meshes"
    obj = meshes / "000_reco.obj"
    mtl = meshes / "000.mtl"
    if not smplx_obj.is_file() or smplx_obj.stat().st_size < 64:
        raise SithReconstructError("SiTH fitted SMPL-X OBJ is missing or implausibly small")
    validate_fit_params(fit_params)
    if not back.is_file():
        raise SithReconstructError("SiTH back image is missing")
    _png_size(back, label="SiTH back image")
    if not obj.is_file() or obj.stat().st_size < 64:
        raise SithReconstructError("SiTH reconstruction OBJ is missing or implausibly small")
    if not mtl.is_file() or mtl.stat().st_size < 10:
        raise SithReconstructError("SiTH reconstruction MTL is missing or implausibly small")
    try:
        obj_text = obj.read_text(encoding="utf-8", errors="strict")
        mtl_text = mtl.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise SithReconstructError("SiTH OBJ/MTL is not valid UTF-8 text") from exc
    mtllib = [line.split(maxsplit=1)[1].strip() for line in obj_text.splitlines() if line.startswith("mtllib ")]
    if mtllib != ["000.mtl"]:
        raise SithReconstructError("SiTH OBJ must reference exactly 000.mtl")
    texture_refs = [line.split(maxsplit=1)[1] for line in mtl_text.splitlines() if line.startswith("map_Kd ")]
    if len(texture_refs) != 1:
        raise SithReconstructError("SiTH MTL must contain exactly one map_Kd texture")
    texture_name = _safe_texture_name(texture_refs[0])
    texture = meshes / texture_name
    if not texture.is_file():
        raise SithReconstructError("SiTH referenced texture file is missing")
    _png_size(texture, label="SiTH reconstruction texture")
    return {
        "smplx_obj_sha256": _sha256(smplx_obj),
        "fit_params_sha256": _sha256(fit_params),
        "back_image_sha256": _sha256(back),
        "mesh_obj_sha256": _sha256(obj),
        "mesh_mtl_sha256": _sha256(mtl),
        "mesh_texture_name": texture_name,
        "mesh_texture_sha256": _sha256(texture),
    }


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SithReconstructError(f"SiTH reconstruction evidence already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def reconstruct_sith(*, workspace: str | Path, distribution: str, repo: str, python: str, diffusion_model: str, diffusion_model_sha256: str, seed: int = DEFAULT_SEED, wsl_exe: str = "wsl.exe") -> dict[str, Any]:
    for label, value in (("distribution", distribution), ("repo", repo), ("python", python), ("diffusion_model", diffusion_model), ("wsl_exe", wsl_exe)):
        if not isinstance(value, str) or not value.strip():
            raise SithReconstructError(f"SiTH {label} is required")
    if not repo.startswith("/") or not python.startswith("/") or not diffusion_model.startswith("/"):
        raise SithReconstructError("SiTH repo/python/model paths must be absolute Linux paths")
    if not isinstance(diffusion_model_sha256, str) or not SHA_RE.fullmatch(diffusion_model_sha256):
        raise SithReconstructError("SiTH diffusion model expected SHA-256 is invalid")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2_147_483_647:
        raise SithReconstructError("SiTH seed must be an integer in 0..2147483647")

    stage, prep, prep_sha = load_prepared_input(workspace)
    evidence_path = stage / "reconstruction.json"
    if evidence_path.exists():
        raise SithReconstructError("SiTH reconstruction already exists; refusing cross-run reuse")
    _require_empty(stage / "smplx", label="SiTH smplx directory")
    _require_empty(stage / "back_images", label="SiTH back_images directory")
    _require_empty(stage / "meshes", label="SiTH meshes directory")

    verify_execution_authority(distribution=distribution, repo=repo, wsl_exe=wsl_exe)
    try:
        model = digest_model_tree(distribution=distribution, python=python, model_path=diffusion_model, wsl_exe=wsl_exe)
    except SithModelError as exc:
        raise SithReconstructError(str(exc)) from exc
    if model["sha256"] != diffusion_model_sha256:
        raise SithReconstructError(f"SiTH diffusion model tree digest mismatch: expected {diffusion_model_sha256}, got {model['sha256']}")

    linux_stage = _linux_path(stage, wsl_exe=wsl_exe, distribution=distribution)
    _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        cwd=repo,
        command=[python, "fit.py", "-i", f"{linux_stage}/images", "-o", f"{linux_stage}/smplx", "--size", "1024", "--opt_orient", "--opt_betas", "--debug"],
        label="SiTH SMPL-X fitting",
    )
    smplx_dir = stage / "smplx"
    smplx_obj = smplx_dir / "000_smplx.obj"
    debug_params = smplx_dir / "debug" / "000.json"
    if not smplx_obj.is_file() or smplx_obj.stat().st_size < 64:
        raise SithReconstructError("SiTH fit did not produce a usable smplx/000_smplx.obj")
    validate_fit_params(debug_params)
    canonical_params = smplx_dir / "000_fit.json"
    shutil.copyfile(debug_params, canonical_params)
    if _sha256(canonical_params) != _sha256(debug_params):
        raise SithReconstructError("SiTH canonical fit parameter copy hash mismatch")
    shutil.rmtree(smplx_dir / "debug", ignore_errors=False)
    if sorted(path.name for path in smplx_dir.iterdir()) != ["000_fit.json", "000_smplx.obj"]:
        raise SithReconstructError("SiTH fit output must reduce to canonical OBJ + fit parameter JSON")

    _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        cwd=repo,
        command=["/usr/bin/env", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "HF_DATASETS_OFFLINE=1", python, "hallucinate.py", "-i", linux_stage, "-o", f"{linux_stage}/back_images", "--pretrained_model_name_or_path", diffusion_model, "--seed", str(seed), "--num_validation_images", "1", "--num_inference_steps", "50"],
        label="SiTH offline back-view hallucination",
    )
    back = stage / "back_images" / "000_000.png"
    if not back.is_file():
        raise SithReconstructError("SiTH hallucination did not produce back_images/000_000.png")
    _png_size(back, label="SiTH back image")

    _checked_wsl(
        wsl_exe=wsl_exe,
        distribution=distribution,
        cwd=repo,
        command=[python, "reconstruct.py", "--test_folder", linux_stage, "--config", "recon/config.yaml", "--resume", "checkpoints/recon_model.pth", "--grid_size", "300", "--save_uv"],
        label="SiTH textured UV reconstruction",
    )
    outputs = validate_reconstruction_outputs(stage)
    evidence = {
        "format": FORMAT,
        "version": VERSION,
        "prepared_input_sha256": prep_sha,
        "subject_track_id": prep["subject_track_id"],
        "sith_revision": SITH_REVISION,
        "diffusion_model_sha256": model["sha256"],
        "diffusion_model_file_count": model["file_count"],
        "diffusion_model_byte_count": model["byte_count"],
        "seed": seed,
        "hallucination": {"num_validation_images": 1, "num_inference_steps": 50, "offline": True},
        "reconstruction": {"grid_size": 300, "save_uv": True, **outputs},
    }
    _write_new_json(evidence_path, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pinned SiTH fit/hallucination/reconstruction stages in a private BodyRig workspace.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--diffusion-model", required=True, help="Absolute Linux path to local offline SiTH diffusion model")
    parser.add_argument("--diffusion-model-sha256", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)
    try:
        evidence = reconstruct_sith(workspace=args.workspace, distribution=args.distribution, repo=args.repo, python=args.python, diffusion_model=args.diffusion_model, diffusion_model_sha256=args.diffusion_model_sha256, seed=args.seed, wsl_exe=args.wsl_exe)
    except (OSError, SithReconstructError) as exc:
        print(f"BodyRig SiTH reconstruction: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"BodyRig SiTH reconstruction: PASS | model={evidence['diffusion_model_sha256'][:12]} | seed={evidence['seed']} | UV mesh ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
