from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-gaussianavatar-preflight"
VERSION = 1
GAUSSIANAVATAR_REPOSITORY = "https://github.com/aipixel/GaussianAvatar"
GAUSSIANAVATAR_COMMIT = "d981c62238ef64e89dcc04719d2ebbb4758b080a"
INSTANTAVATAR_REPOSITORY = "https://github.com/tijiang13/InstantAvatar"
INSTANTAVATAR_COMMIT = "3cdfd49d00a5e6c1ebde4d6ae2784b5d6f7cd2bc"
BENCHMARK_SMPL_TYPE = "smpl"

# Benchmark v1 deliberately follows the public own-video pipeline, which fits
# SMPL. GaussianAvatar's trainer contains an SMPL-X path, but its published
# own-video canonical-map scripts remain SMPL-specific. Do not claim SMPL-X
# authority until BodyRig has an independently validated SMPL-X materializer.
REQUIRED_FEMALE_SMPL_ASSETS: tuple[str, ...] = (
    "smpl_files/smpl/SMPL_FEMALE.pkl",
    "template_mesh_smpl_uv.obj",
    "uv_masks/uv_mask512_with_faceid_smpl.npy",
    "smpl_faces.npy",
    "lbs_map_smpl_512.npy",
)


class PhotorealGaussianAvatarPreflightError(ValueError):
    pass


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, label: str) -> str:
    try:
        completed = subprocess.run(
            argv,
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
        raise PhotorealGaussianAvatarPreflightError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stdout or "")[-5000:].strip()
        raise PhotorealGaussianAvatarPreflightError(
            f"{label} failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
        )
    return (completed.stdout or "").strip()


def _git(path: Path, *args: str) -> str:
    return _run(["git", "-C", str(path), *args], label=f"git {' '.join(args)} in {path.name}")


def _repo_record(path: Path, *, expected_commit: str, label: str) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    record: dict[str, Any] = {
        "label": label,
        "path": str(path),
        "present": path.is_dir(),
        "expected_commit": expected_commit,
        "observed_commit": None,
        "clean": False,
    }
    if not path.is_dir():
        blockers.append(f"missing pinned repository: {label}")
        return record, blockers
    try:
        observed = _git(path, "rev-parse", "HEAD").strip().lower()
        clean = _git(path, "status", "--porcelain") == ""
    except PhotorealGaussianAvatarPreflightError as exc:
        blockers.append(str(exc))
        return record, blockers
    record["observed_commit"] = observed
    record["clean"] = clean
    if observed != expected_commit:
        blockers.append(f"repository commit mismatch: {label}: expected {expected_commit}, observed {observed}")
    if not clean:
        blockers.append(f"repository checkout is dirty: {label}")
    return record, blockers


def build_gaussianavatar_preflight(
    *,
    gaussianavatar_root: str | Path,
    instantavatar_root: str | Path,
    asset_root: str | Path,
    smpl_gender: str,
) -> dict[str, Any]:
    gender = str(smpl_gender or "").strip().lower()
    if gender != "female":
        raise PhotorealGaussianAvatarPreflightError(
            "Performer 42 GaussianAvatar benchmark v1 requires explicit smpl_gender=female"
        )
    ga_root = Path(gaussianavatar_root).expanduser().resolve()
    ia_root = Path(instantavatar_root).expanduser().resolve()
    assets = Path(asset_root).expanduser().resolve()

    ga_record, ga_blockers = _repo_record(
        ga_root, expected_commit=GAUSSIANAVATAR_COMMIT, label="GaussianAvatar"
    )
    ia_record, ia_blockers = _repo_record(
        ia_root, expected_commit=INSTANTAVATAR_COMMIT, label="InstantAvatar preprocessing"
    )
    blockers = [*ga_blockers, *ia_blockers]

    asset_records: list[dict[str, Any]] = []
    for relative in REQUIRED_FEMALE_SMPL_ASSETS:
        path = assets / relative
        present = path.is_file() and path.stat().st_size > 0
        record: dict[str, Any] = {
            "relative_path": relative,
            "present": present,
            "size_bytes": path.stat().st_size if present else 0,
            "sha256": _file_sha(path) if present else None,
            "operator_supplied": True,
        }
        if not present:
            blockers.append(f"missing GaussianAvatar benchmark asset: {relative}")
        asset_records.append(record)

    # The public own-video pipeline also invokes external OpenPose/SAM/ROMP
    # tooling. Their model/runtime setup is a separate executable preflight;
    # this source/asset gate must not pretend that code checkout == runnable.
    tool_presence = {
        "git": shutil.which("git") is not None,
    }
    if not tool_presence["git"]:
        blockers.append("git executable is unavailable")

    blockers = sorted(set(blockers))
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "benchmark": "gaussianavatar",
        "gaussianavatar_repository": GAUSSIANAVATAR_REPOSITORY,
        "gaussianavatar_commit": GAUSSIANAVATAR_COMMIT,
        "instantavatar_repository": INSTANTAVATAR_REPOSITORY,
        "instantavatar_commit": INSTANTAVATAR_COMMIT,
        "repositories": [ga_record, ia_record],
        "smpl_gender": "female",
        "smpl_gender_explicit": True,
        "smpl_type": BENCHMARK_SMPL_TYPE,
        "smplx_training_path_claimed": False,
        "female_geometry_prior_only": True,
        "assets": asset_records,
        "tool_presence": tool_presence,
        "source_asset_preflight_ready": not blockers,
        "execution_runtime_preflight_required": True,
        "execution_runtime_ready": False,
        "blockers": blockers,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_dependency_authorized": False,
        "production_activation": False,
    }
    result["preflight_sha256"] = _digest(result, omit="preflight_sha256")
    return result
