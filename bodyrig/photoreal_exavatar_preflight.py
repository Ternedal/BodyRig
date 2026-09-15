from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-exavatar-preflight"
VERSION = 1
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"

REPOSITORIES: tuple[tuple[str, str, str], ...] = (
    ("exavatar", "https://github.com/mks0601/ExAvatar_RELEASE", UPSTREAM_COMMIT),
    ("deca", "https://github.com/yfeng95/DECA", "a11554ae2a2b0f3998cf1fa94dd4db03babb34a2"),
    ("hand4whole", "https://github.com/mks0601/Hand4Whole_RELEASE", "c94908654b8108f241f18f04b4a493c05137edf6"),
    ("mmpose", "https://github.com/open-mmlab/mmpose", "759b39c13fea6ba094afc1fa932f51dc1b11cbf9"),
    ("segment-anything", "https://github.com/facebookresearch/segment-anything", "dca509fe793f601edb92606367a655c15ac00fdf"),
    ("depth-anything-v2", "https://github.com/DepthAnything/Depth-Anything-V2", "a561b849ebae10a6f5ef49e26c83cbbcd36c71bf"),
    ("diff-gaussian-rasterization-depth", "https://github.com/leo-frank/diff-gaussian-rasterization-depth", "03f0b7d00383d6e96c22b37325ac9e5450947bf5"),
)

PUBLIC_TOOL_LAYOUT = {
    "exavatar": "ExAvatar_RELEASE",
    "deca": "DECA",
    "hand4whole": "Hand4Whole_RELEASE",
    "mmpose": "mmpose",
    "segment-anything": "segment-anything",
    "depth-anything-v2": "Depth-Anything-V2",
    "diff-gaussian-rasterization-depth": "diff-gaussian-rasterization-depth",
}

ASSET_LAYOUT: tuple[tuple[str, str, bool], ...] = (
    ("deca_model", "deca/deca_model.tar", False),
    ("deca_flame_female", "deca/FLAME2020/female_model.pkl", True),
    ("deca_flame_male", "deca/FLAME2020/male_model.pkl", True),
    ("deca_flame_generic", "deca/generic_model.pkl", True),
    ("hand4whole_snapshot", "hand4whole/snapshot_6.pth.tar", False),
    ("sam_vit_h", "sam/sam_vit_h_4b8939.pth", False),
    ("depth_anything_vitl", "depth-anything-v2/depth_anything_v2_vitl.pth", False),
    ("smplx_neutral", "human_model_files/smplx/SMPLX_NEUTRAL.npz", True),
    ("smplx_male", "human_model_files/smplx/SMPLX_MALE.npz", True),
    ("smplx_female", "human_model_files/smplx/SMPLX_FEMALE.npz", True),
    ("smplx_flame_vertex_ids", "human_model_files/smplx/SMPL-X__FLAME_vertex_ids.npy", True),
    ("mano_smplx_vertex_ids", "human_model_files/smplx/MANO_SMPLX_vertex_ids.pkl", True),
    ("smplx_flip_correspondences", "human_model_files/smplx/smplx_flip_correspondences.npz", True),
    ("flame_neutral", "human_model_files/flame/FLAME_NEUTRAL.pkl", True),
    ("flame_male", "human_model_files/flame/FLAME_MALE.pkl", True),
    ("flame_female", "human_model_files/flame/FLAME_FEMALE.pkl", True),
    ("flame_2019_generic", "human_model_files/flame/2019/generic_model.pkl", True),
)

REFERENCE_ASSETS: tuple[tuple[str, str], ...] = (
    ("rtmpose_wholebody", "weights/rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.pth"),
    ("rtmdet_person", "weights/rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth"),
)


class PhotorealExAvatarPreflightError(ValueError):
    pass


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(path: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _asset_record(root: Path, name: str, relative: str, restricted: bool) -> tuple[dict[str, Any], str | None]:
    path = root / Path(relative)
    record: dict[str, Any] = {
        "name": name,
        "relative_path": relative,
        "restricted_or_operator_supplied": restricted,
        "present": path.is_file(),
        "size_bytes": 0,
        "sha256": None,
    }
    if not path.is_file():
        return record, f"missing asset: {relative}"
    size = path.stat().st_size
    if size < 1:
        return record, f"empty asset: {relative}"
    record["size_bytes"] = size
    record["sha256"] = _file_sha(path)
    return record, None


def _repo_record(root: Path, name: str, url: str, expected_commit: str) -> tuple[dict[str, Any], list[str]]:
    relative = PUBLIC_TOOL_LAYOUT[name]
    path = root / relative
    record: dict[str, Any] = {
        "name": name,
        "repository": url,
        "relative_path": relative,
        "expected_commit": expected_commit,
        "present": path.is_dir(),
        "observed_commit": None,
        "clean": False,
        "commit_match": False,
    }
    blockers: list[str] = []
    if not path.is_dir():
        blockers.append(f"missing public dependency checkout: {relative}")
        return record, blockers
    observed = _git(path, "rev-parse", "HEAD")
    if observed is None:
        blockers.append(f"dependency is not a readable git checkout: {relative}")
        return record, blockers
    observed = observed.lower()
    record["observed_commit"] = observed
    record["commit_match"] = observed == expected_commit
    if observed != expected_commit:
        blockers.append(f"dependency commit mismatch: {name}")
    status = _git(path, "status", "--porcelain")
    if status is None:
        blockers.append(f"dependency git status failed: {name}")
    else:
        record["clean"] = status == ""
        if status != "":
            blockers.append(f"dependency checkout is dirty: {name}")
    return record, blockers


def build_exavatar_preflight(
    *,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    require_colmap: bool = True,
) -> dict[str, Any]:
    deps = Path(dependency_root).expanduser().resolve()
    assets = Path(asset_root).expanduser().resolve()
    reference = Path(reference_model_root).expanduser().resolve()
    gender = str(smplx_gender or "").strip().lower()
    if gender not in {"female", "male", "neutral"}:
        raise PhotorealExAvatarPreflightError("smplx_gender must be explicitly female, male or neutral")

    blockers: list[str] = []
    if not deps.is_dir():
        blockers.append(f"dependency root missing: {deps}")
    if not assets.is_dir():
        blockers.append(f"asset root missing: {assets}")
    if not reference.is_dir():
        blockers.append(f"reference model root missing: {reference}")

    repo_records: list[dict[str, Any]] = []
    if deps.is_dir():
        for name, url, commit in REPOSITORIES:
            record, repo_blockers = _repo_record(deps, name, url, commit)
            repo_records.append(record)
            blockers.extend(repo_blockers)
    else:
        for name, url, commit in REPOSITORIES:
            repo_records.append(
                {
                    "name": name,
                    "repository": url,
                    "relative_path": PUBLIC_TOOL_LAYOUT[name],
                    "expected_commit": commit,
                    "present": False,
                    "observed_commit": None,
                    "clean": False,
                    "commit_match": False,
                }
            )

    asset_records: list[dict[str, Any]] = []
    if assets.is_dir():
        for name, relative, restricted in ASSET_LAYOUT:
            record, blocker = _asset_record(assets, name, relative, restricted)
            asset_records.append(record)
            if blocker:
                blockers.append(blocker)
    else:
        for name, relative, restricted in ASSET_LAYOUT:
            asset_records.append(
                {
                    "name": name,
                    "relative_path": relative,
                    "restricted_or_operator_supplied": restricted,
                    "present": False,
                    "size_bytes": 0,
                    "sha256": None,
                }
            )

    reference_records: list[dict[str, Any]] = []
    if reference.is_dir():
        for name, relative in REFERENCE_ASSETS:
            record, blocker = _asset_record(reference, name, relative, False)
            reference_records.append(record)
            if blocker:
                blockers.append(f"reference vision {blocker}")
    else:
        for name, relative in REFERENCE_ASSETS:
            reference_records.append(
                {
                    "name": name,
                    "relative_path": relative,
                    "restricted_or_operator_supplied": False,
                    "present": False,
                    "size_bytes": 0,
                    "sha256": None,
                }
            )

    executable_records: list[dict[str, Any]] = []
    for executable, required in (("git", True), ("nvcc", True), ("colmap", bool(require_colmap))):
        resolved = shutil.which(executable)
        executable_records.append(
            {
                "name": executable,
                "required": required,
                "present": resolved is not None,
                "resolved_path": resolved,
            }
        )
        if required and resolved is None:
            blockers.append(f"required executable missing: {executable}")

    blockers = sorted(set(blockers))
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "upstream_commit": UPSTREAM_COMMIT,
        "smplx_gender": gender,
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "dependency_root": str(deps),
        "asset_root": str(assets),
        "reference_model_root": str(reference),
        "repositories": repo_records,
        "assets": asset_records,
        "reference_vision_assets": reference_records,
        "executables": executable_records,
        "operator_supplied_restricted_assets_required": True,
        "automatic_restricted_asset_download": False,
        "require_colmap": bool(require_colmap),
        "benchmark_environment_ready": not blockers,
        "blockers": blockers,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    result["preflight_sha256"] = hashlib.sha256(canonical).hexdigest()
    return result


def build_exavatar_preflight_files(
    *,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    output_path: str | Path,
    require_colmap: bool = True,
) -> dict[str, Any]:
    result = build_exavatar_preflight(
        dependency_root=dependency_root,
        asset_root=asset_root,
        reference_model_root=reference_model_root,
        smplx_gender=smplx_gender,
        require_colmap=require_colmap,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealExAvatarPreflightError(f"ExAvatar preflight output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
