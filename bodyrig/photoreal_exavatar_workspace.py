from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .photoreal_exavatar_preflight import PUBLIC_TOOL_LAYOUT, REPOSITORIES, UPSTREAM_COMMIT
from .photoreal_exavatar_preflight_strict import STRICT_FLAME_ASSETS

MATERIALIZATION_FORMAT = "bodyrig-photoreal-exavatar-materialization-receipt"
PREFLIGHT_FORMAT = "bodyrig-photoreal-exavatar-preflight"
WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
VERSION = 1
SITH_REVISION = "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d"
SITH_REMOTES = {
    "https://github.com/SiTH-Diffusion/SiTH.git",
    "https://github.com/SiTH-Diffusion/SiTH",
}



class PhotorealExAvatarWorkspaceError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarWorkspaceError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealExAvatarWorkspaceError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarWorkspaceError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_subject_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise PhotorealExAvatarWorkspaceError("performer_id is empty")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    if not safe or len(safe) > 96:
        raise PhotorealExAvatarWorkspaceError("performer_id cannot form a safe ExAvatar subject id")
    return f"bodyrig-{safe}"


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
        raise PhotorealExAvatarWorkspaceError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stdout or "")[-6000:].strip()
        raise PhotorealExAvatarWorkspaceError(
            f"{label} failed with exit code {completed.returncode}" + (f": {tail}" if tail else "")
        )
    return (completed.stdout or "").strip()


def _git(path: Path, *args: str) -> str:
    resolved = path.expanduser().resolve()
    return _run(
        ["git", "-c", f"safe.directory={resolved}", "-C", str(resolved), *args],
        label=f"git {' '.join(args)} in {path.name}",
    )


def _clone_pinned(
    source: Path,
    destination: Path,
    repository_url: str,
    expected_commit: str,
) -> None:
    if not source.is_dir():
        raise PhotorealExAvatarWorkspaceError(f"pinned dependency source missing: {source}")
    resolved_source = source.expanduser().resolve()
    observed_source = _git(resolved_source, "rev-parse", "HEAD").lower()
    if observed_source != expected_commit:
        raise PhotorealExAvatarWorkspaceError(
            f"pinned dependency commit mismatch before workspace clone: {source.name}"
        )
    if _git(resolved_source, "status", "--porcelain") != "":
        raise PhotorealExAvatarWorkspaceError(
            f"pinned dependency is dirty before workspace clone: {source.name}"
        )

    url = str(repository_url or "").strip()
    if not url.startswith("https://github.com/") or "\n" in url or "\r" in url:
        raise PhotorealExAvatarWorkspaceError(
            f"pinned dependency repository URL is invalid: {source.name}"
        )

    _run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            url,
            str(destination),
        ],
        label=f"clone {destination.name} from pinned public repository",
    )
    _run(
        ["git", "-C", str(destination), "checkout", "--detach", expected_commit],
        label=f"checkout {destination.name}",
    )
    _run(
        [
            "git",
            "-C",
            str(destination),
            "submodule",
            "update",
            "--init",
            "--recursive",
        ],
        label=f"initialize submodules for {destination.name}",
    )

    observed = _git(destination, "rev-parse", "HEAD").lower()
    if observed != expected_commit:
        raise PhotorealExAvatarWorkspaceError(
            f"workspace dependency commit mismatch: {destination.name}"
        )
    if _git(destination, "status", "--porcelain") != "":
        raise PhotorealExAvatarWorkspaceError(
            f"fresh workspace dependency is dirty: {destination.name}"
        )


def _resolve_pinned_sith_uv_template(sith_root: Path | None = None) -> Path:
    root = (
        sith_root.expanduser().resolve()
        if sith_root is not None
        else (Path.home() / ".local" / "share" / "bodyrig" / "sith").resolve()
    )
    if not root.is_dir() or not (root / ".git").is_dir():
        raise PhotorealExAvatarWorkspaceError(
            f"pinned SiTH checkout missing for canonical SMPL-X UV template: {root}"
        )
    origin = _git(root, "remote", "get-url", "origin").strip()
    if origin not in SITH_REMOTES:
        raise PhotorealExAvatarWorkspaceError(
            f"pinned SiTH checkout has unexpected origin: {origin}"
        )
    observed = _git(root, "rev-parse", "HEAD").strip().lower()
    if observed != SITH_REVISION:
        raise PhotorealExAvatarWorkspaceError(
            f"pinned SiTH checkout revision mismatch: {observed}"
        )
    if _git(root, "status", "--porcelain", "--untracked-files=no") != "":
        raise PhotorealExAvatarWorkspaceError(
            "pinned SiTH checkout has modified tracked files"
        )
    template = root / "data" / "smplx_uv.obj"
    if not template.is_file() or template.stat().st_size < 1:
        raise PhotorealExAvatarWorkspaceError(
            f"pinned SiTH canonical SMPL-X UV template missing: {template}"
        )
    try:
        lines = template.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PhotorealExAvatarWorkspaceError(
            "pinned SiTH canonical SMPL-X UV template is unreadable"
        ) from exc
    if not any(line.startswith("vt ") for line in lines) or not any(
        line.startswith("f ") and "/" in line for line in lines
    ):
        raise PhotorealExAvatarWorkspaceError(
            "pinned SiTH canonical SMPL-X UV template lacks UV topology"
        )
    return template


def _validate_preflight(preflight: Mapping[str, Any], *, smplx_gender: str) -> str:
    if preflight.get("format") != PREFLIGHT_FORMAT or preflight.get("version") != VERSION:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight format/version mismatch")
    if preflight.get("upstream_commit") != UPSTREAM_COMMIT:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight targets different upstream commit")
    if preflight.get("strict_upstream_asset_inventory") is not True:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight is not strict-upstream complete")
    if preflight.get("benchmark_environment_ready") is not True or preflight.get("blockers") != []:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight does not authorize workspace preparation")
    if preflight.get("smplx_gender") != smplx_gender or preflight.get("smplx_gender_explicit") is not True:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight SMPL-X gender mismatch")
    if preflight.get("upstream_default_gender_accepted") is not False:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight accepted upstream gender default")
    if preflight.get("automatic_restricted_asset_download") is not False:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight enabled restricted asset download")
    if preflight.get("photoreal_acceptance_authority") is not False or preflight.get("production_activation") is not False:
        raise PhotorealExAvatarWorkspaceError("ExAvatar preflight crossed downstream authority")
    declared = _sha(preflight.get("preflight_sha256"), label="ExAvatar preflight SHA-256")
    if _canonical_digest(preflight, omit="preflight_sha256") != declared:
        raise PhotorealExAvatarWorkspaceError("ExAvatar strict preflight digest mismatch")
    return declared


def _validate_materialization(receipt: Mapping[str, Any], dataset_dir: Path) -> str:
    if receipt.get("format") != MATERIALIZATION_FORMAT or receipt.get("version") != VERSION:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization receipt format/version mismatch")
    if receipt.get("upstream_commit") != UPSTREAM_COMMIT:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization targets different upstream commit")
    if receipt.get("held_out_evaluation_disclosed") is not False or receipt.get("original_video_copied") is not False:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization disclosed forbidden source/eval data")
    if receipt.get("frame_lists_are_training_only") is not True or receipt.get("bodyrig_held_out_evaluation_is_external") is not True:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization train/eval boundary is invalid")
    if receipt.get("exact_p0_frame_hashes_reproduced") is not True:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization did not reproduce P0 frame hashes")
    if receipt.get("photoreal_acceptance_authority") is not False or receipt.get("production_activation") is not False:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization crossed downstream authority")
    frames = receipt.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization contains no frames")
    if int(receipt.get("frame_count") or 0) != len(frames):
        raise PhotorealExAvatarWorkspaceError("ExAvatar materialization frame count mismatch")
    if (dataset_dir / "video.mp4").exists():
        raise PhotorealExAvatarWorkspaceError("materialized dataset unexpectedly contains original video.mp4")
    if not (dataset_dir / "frame_list_test.txt").is_file() or (dataset_dir / "frame_list_test.txt").read_text(encoding="utf-8") != "":
        raise PhotorealExAvatarWorkspaceError("materialized dataset exposed an ExAvatar test split")
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise PhotorealExAvatarWorkspaceError("materialization frame entry is invalid")
        index = frame.get("exavatar_frame_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise PhotorealExAvatarWorkspaceError("materialization frame index is invalid")
        relative = str(frame.get("relative_path") or "")
        if relative != f"frames/{index}.png":
            raise PhotorealExAvatarWorkspaceError("materialization frame path is not canonical")
        path = dataset_dir / relative
        if not path.is_file():
            raise PhotorealExAvatarWorkspaceError(f"materialized frame missing: {relative}")
        if _file_sha(path) != _sha(frame.get("staged_png_sha256"), label="materialized PNG SHA-256"):
            raise PhotorealExAvatarWorkspaceError(f"materialized frame SHA mismatch: {relative}")
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _preflight_asset_map(preflight: Mapping[str, Any], *, key: str) -> dict[str, dict[str, Any]]:
    values = preflight.get(key)
    if not isinstance(values, list):
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar preflight {key} is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealExAvatarWorkspaceError(f"ExAvatar preflight {key} entry is invalid")
        relative = str(raw.get("relative_path") or "")
        if not relative or relative in result or raw.get("present") is not True:
            raise PhotorealExAvatarWorkspaceError(f"ExAvatar preflight {key} contains invalid asset record")
        result[relative] = dict(raw)
    return result


def _verify_asset(root: Path, relative: str, records: Mapping[str, Mapping[str, Any]]) -> Path:
    record = records.get(relative)
    if record is None:
        raise PhotorealExAvatarWorkspaceError(f"asset missing from strict preflight provenance: {relative}")
    path = root / relative
    if not path.is_file():
        raise PhotorealExAvatarWorkspaceError(f"asset disappeared after preflight: {relative}")
    expected = _sha(record.get("sha256"), label=f"asset SHA-256 {relative}")
    if _file_sha(path) != expected:
        raise PhotorealExAvatarWorkspaceError(f"asset changed after preflight: {relative}")
    return path


def _link_internal_directory(target: Path, link: Path) -> None:
    resolved_target = target.resolve()
    if not resolved_target.is_dir():
        raise PhotorealExAvatarWorkspaceError(
            f"internal workspace link target is missing: {target}"
        )
    if link.exists() or link.is_symlink():
        raise PhotorealExAvatarWorkspaceError(
            f"internal workspace link destination already exists: {link}"
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    relative_target = os.path.relpath(resolved_target, start=link.parent.resolve())
    link.symlink_to(relative_target, target_is_directory=True)
    if not link.is_symlink() or link.resolve() != resolved_target:
        raise PhotorealExAvatarWorkspaceError(
            f"internal workspace link did not resolve to target: {link}"
        )


def _link_file(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise PhotorealExAvatarWorkspaceError(f"workspace asset destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source)


def _stage_flame_static_embedding(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"FLAME static embedding source missing: {source}")
    if destination.exists() or destination.is_symlink():
        raise PhotorealExAvatarWorkspaceError(f"workspace asset destination already exists: {destination}")
    raw = source.read_bytes()
    if b"lmk_face_idx" not in raw or b"lmk_b_coords" not in raw:
        raise PhotorealExAvatarWorkspaceError("FLAME static embedding does not expose expected landmark keys")
    staged = raw
    if b"\r" in raw:
        # Legacy FLAME protocol-0 pickles are text pickles. CRLF/CR line endings
        # trigger "_pickle.UnpicklingError: the STRING opcode argument must be quoted"
        # under Linux. Normalize only the isolated workspace copy.
        staged = b"\n".join(raw.splitlines()) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(staged)
    return _file_sha(destination)


def _copy_patch(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar patch source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    before_sha = _file_sha(destination) if destination.is_file() else None
    shutil.copy2(source, destination)
    return {
        "destination": destination.as_posix(),
        "source_sha256": _file_sha(source),
        "replaced_sha256": before_sha,
        "patched_sha256": _file_sha(destination),
    }


def _copy_deca_dataset_with_pinned_face_keypoints(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar DECA dataset patch source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    replaced_sha = _file_sha(destination) if destination.is_file() else None
    raw = source.read_text(encoding="utf-8")

    import_marker = "import scipy.io\n"
    detector_import_marker = "from . import detectors\n"
    detector_init_marker = (
        "        if face_detector == 'fan':\n"
        "            self.face_detector = detectors.FAN()\n"
        "        # elif face_detector == 'mtcnn':\n"
        "        #     self.face_detector = detectors.MTCNN()\n"
        "        else:\n"
        "            print(f'please check the detector: {face_detector}')\n"
        "            exit()\n"
    )
    detector_run_marker = (
        "            else:\n"
        "                bbox, bbox_type = self.face_detector.run(image)\n"
        "                if len(bbox) < 4:\n"
        "                    print('no face detected! run original image')\n"
        "                    left = 0; right = h-1; top=0; bottom=w-1\n"
        "                    is_valid = False\n"
        "                else:\n"
        "                    left = bbox[0]; right=bbox[2]\n"
        "                    top = bbox[1]; bottom=bbox[3]\n"
        "                old_size, center = self.bbox2point(left, right, top, bottom, type=bbox_type)\n"
    )
    if (
        raw.count(import_marker) != 1
        or raw.count(detector_import_marker) != 1
        or raw.count(detector_init_marker) != 1
        or raw.count(detector_run_marker) != 1
    ):
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar DECA face-detector markers changed")

    patched = raw.replace(import_marker, import_marker + "import json\n", 1)
    patched = patched.replace(detector_import_marker, "", 1)
    patched = patched.replace(
        detector_init_marker,
        (
            "        if face_detector != 'fan':\n"
            "            raise RuntimeError('BodyRig DECA patch requires the pinned whole-body keypoint path')\n"
            "        self.face_detector = None\n"
        ),
        1,
    )
    patched = patched.replace(
        detector_run_marker,
        (
            "            else:\n"
            "                bodyrig_kpt_path = os.path.join(os.path.dirname(os.path.dirname(imagepath)), 'keypoints_whole_body', imagename + '.json')\n"
            "                if not os.path.isfile(bodyrig_kpt_path):\n"
            "                    raise RuntimeError('BodyRig whole-body keypoints missing for DECA frame {}'.format(imagename))\n"
            "                with open(bodyrig_kpt_path) as f:\n"
            "                    bodyrig_kpt = np.array(json.load(f), dtype=np.float32)\n"
            "                if bodyrig_kpt.ndim != 2 or bodyrig_kpt.shape[0] < 91 or bodyrig_kpt.shape[1] < 3:\n"
            "                    raise RuntimeError('BodyRig whole-body keypoints invalid for DECA frame {}'.format(imagename))\n"
            "                bodyrig_face = bodyrig_kpt[23:91]\n"
            "                bodyrig_valid = bodyrig_face[:,2] > 0.5\n"
            "                if int(bodyrig_valid.sum()) < 5:\n"
            "                    print('BodyRig face keypoints insufficient; mark DECA frame invalid and use original image')\n"
            "                    left = 0; right = w-1; top = 0; bottom = h-1\n"
            "                    is_valid = False\n"
            "                    old_size, center = self.bbox2point(left, right, top, bottom, type='bbox')\n"
            "                else:\n"
            "                    bodyrig_xy = bodyrig_face[bodyrig_valid,:2]\n"
            "                    left = np.min(bodyrig_xy[:,0]); right = np.max(bodyrig_xy[:,0])\n"
            "                    top = np.min(bodyrig_xy[:,1]); bottom = np.max(bodyrig_xy[:,1])\n"
            "                    old_size, center = self.bbox2point(left, right, top, bottom, type='kpt68')\n"
        ),
        1,
    )
    destination.write_text(patched, encoding="utf-8")
    return {
        "destination": destination.as_posix(),
        "source_sha256": _file_sha(source),
        "replaced_sha256": replaced_sha,
        "patched_sha256": _file_sha(destination),
    }


def _copy_sam_with_temporal_bbox_fallback(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar SAM patch source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    replaced_sha = _file_sha(destination) if destination.is_file() else None
    raw = source.read_text(encoding="utf-8")

    setup_marker = (
        "frame_idx_list = sorted([int(x.split('/')[-1][:-4]) for x in img_path_list])\n"
        "img_height, img_width = cv2.imread(img_path_list[0]).shape[:2]\n"
        "video_save = cv2.VideoWriter(osp.join(root_path, 'masks.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 30, (img_width*2, img_height))\n"
    )
    setup_replacement = (
        "frame_idx_list = sorted([int(x.split('/')[-1][:-4]) for x in img_path_list])\n"
        "img_height, img_width = cv2.imread(img_path_list[0]).shape[:2]\n"
        "\n"
        "# BodyRig: preserve upstream >0.5 SAM point prompts, but repair only invalid/empty prompt boxes\n"
        "# from neighboring frames so sparse keypoint frames can use SAM's supported box-only path.\n"
        "bodyrig_sam_points = {}\n"
        "bodyrig_sam_seed_bbox = {}\n"
        "for bodyrig_frame_idx in frame_idx_list:\n"
        "    bodyrig_kpt_path = osp.join(root_path, 'keypoints_whole_body', str(bodyrig_frame_idx) + '.json')\n"
        "    with open(bodyrig_kpt_path) as f:\n"
        "        bodyrig_all_kpt = np.array(json.load(f), dtype=np.float32)\n"
        "    bodyrig_points = bodyrig_all_kpt[bodyrig_all_kpt[:,2] > 0.5,:2]\n"
        "    bodyrig_sam_points[bodyrig_frame_idx] = bodyrig_points\n"
        "    if bodyrig_points.shape[0] >= 2:\n"
        "        bodyrig_bbox = get_bbox(bodyrig_points, np.ones_like(bodyrig_points[:,0]))\n"
        "        if np.all(np.isfinite(bodyrig_bbox)) and float(bodyrig_bbox[2]) > 1e-6 and float(bodyrig_bbox[3]) > 1e-6:\n"
        "            bodyrig_bbox[2:] += bodyrig_bbox[:2] # xywh -> xyxy\n"
        "            bodyrig_sam_seed_bbox[bodyrig_frame_idx] = bodyrig_bbox.astype(np.float32)\n"
        "if not bodyrig_sam_seed_bbox:\n"
        "    raise RuntimeError('BodyRig ExAvatar SAM has no valid >0.5 bbox seeds')\n"
        "bodyrig_valid_indices = sorted(bodyrig_sam_seed_bbox)\n"
        "bodyrig_sam_bbox = {}\n"
        "for bodyrig_frame_idx in frame_idx_list:\n"
        "    if bodyrig_frame_idx in bodyrig_sam_seed_bbox:\n"
        "        bodyrig_sam_bbox[bodyrig_frame_idx] = bodyrig_sam_seed_bbox[bodyrig_frame_idx].copy()\n"
        "        continue\n"
        "    bodyrig_left = [x for x in bodyrig_valid_indices if x < bodyrig_frame_idx]\n"
        "    bodyrig_right = [x for x in bodyrig_valid_indices if x > bodyrig_frame_idx]\n"
        "    bodyrig_left_idx = bodyrig_left[-1] if bodyrig_left else None\n"
        "    bodyrig_right_idx = bodyrig_right[0] if bodyrig_right else None\n"
        "    if bodyrig_left_idx is not None and bodyrig_right_idx is not None:\n"
        "        bodyrig_alpha = float(bodyrig_frame_idx - bodyrig_left_idx) / float(bodyrig_right_idx - bodyrig_left_idx)\n"
        "        bodyrig_bbox = bodyrig_sam_seed_bbox[bodyrig_left_idx] * (1.0 - bodyrig_alpha) + bodyrig_sam_seed_bbox[bodyrig_right_idx] * bodyrig_alpha\n"
        "        bodyrig_mode = 'interpolated'\n"
        "    elif bodyrig_left_idx is not None:\n"
        "        bodyrig_bbox = bodyrig_sam_seed_bbox[bodyrig_left_idx].copy()\n"
        "        bodyrig_mode = 'previous'\n"
        "    else:\n"
        "        bodyrig_bbox = bodyrig_sam_seed_bbox[bodyrig_right_idx].copy()\n"
        "        bodyrig_mode = 'next'\n"
        "    bodyrig_sam_bbox[bodyrig_frame_idx] = bodyrig_bbox.astype(np.float32)\n"
        "    print('BodyRig ExAvatar SAM bbox fallback: {} for frame {}'.format(bodyrig_mode, bodyrig_frame_idx))\n"
        "\n"
        "video_save = cv2.VideoWriter(osp.join(root_path, 'masks.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 30, (img_width*2, img_height))\n"
    )

    prompt_marker = (
        "    # load keypoints\n"
        "    kpt_path = osp.join(root_path, 'keypoints_whole_body', str(frame_idx) + '.json')\n"
        "    with open(kpt_path) as f:\n"
        "        kpt = np.array(json.load(f), dtype=np.float32)\n"
        "    kpt = kpt[kpt[:,2] > 0.5,:2]\n"
        "    bbox = get_bbox(kpt, np.ones_like(kpt[:,0]))\n"
        "    bbox[2:] += bbox[:2] # xywh -> xyxy\n"
    )
    prompt_replacement = (
        "    # BodyRig: use the exact upstream >0.5 point prompts when available.\n"
        "    # Sparse frames keep the temporally repaired bbox and may run box-only.\n"
        "    kpt = bodyrig_sam_points[frame_idx]\n"
        "    bbox = bodyrig_sam_bbox[frame_idx].copy()\n"
        "    point_coords = kpt if kpt.shape[0] > 0 else None\n"
        "    point_labels = np.ones_like(kpt[:,0]) if kpt.shape[0] > 0 else None\n"
    )

    predict_marker = (
        "    masks, scores, logits = predictor.predict(point_coords=kpt, point_labels=np.ones_like(kpt[:,0]), box=bbox[None,:], multimask_output=False)\n"
        "    mask_input = logits[np.argmax(scores), :, :]\n"
        "    masks, _, _ = predictor.predict(point_coords=kpt, point_labels=np.ones_like(kpt[:,0]), box=bbox[None,:], multimask_output=False, mask_input=mask_input[None])\n"
    )
    predict_replacement = (
        "    masks, scores, logits = predictor.predict(point_coords=point_coords, point_labels=point_labels, box=bbox[None,:], multimask_output=False)\n"
        "    mask_input = logits[np.argmax(scores), :, :]\n"
        "    masks, _, _ = predictor.predict(point_coords=point_coords, point_labels=point_labels, box=bbox[None,:], multimask_output=False, mask_input=mask_input[None])\n"
    )

    if raw.count(setup_marker) != 1 or raw.count(prompt_marker) != 1 or raw.count(predict_marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar SAM markers changed")
    patched = raw.replace(setup_marker, setup_replacement, 1)
    patched = patched.replace(prompt_marker, prompt_replacement, 1)
    patched = patched.replace(predict_marker, predict_replacement, 1)
    destination.write_text(patched, encoding="utf-8")
    return {
        "destination": destination.as_posix(),
        "source_sha256": _file_sha(source),
        "replaced_sha256": replaced_sha,
        "patched_sha256": _file_sha(destination),
    }


def _patch_exavatar_custom_dataset_body_bboxes(source: Path) -> dict[str, Any]:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"pinned ExAvatar Custom dataset source missing: {source}")
    raw = source.read_text(encoding="utf-8")
    before_sha = _file_sha(source)

    init_marker = (
        "        self.cam_params, self.img_paths, self.kpts, self.smplx_params, self.flame_params, self.flame_shape_param, self.frame_idx_list = self.load_data()\n"
        "        self.get_smplx_trans_init() # get initial smplx translation \n"
    )
    init_replacement = (
        "        self.cam_params, self.img_paths, self.kpts, self.smplx_params, self.flame_params, self.flame_shape_param, self.frame_idx_list = self.load_data()\n"
        "        self.body_bboxes = self.get_body_bbox_init()\n"
        "        self.get_smplx_trans_init() # get initial smplx translation \n"
    )

    trans_marker = (
        "    def get_smplx_trans_init(self):\n"
        "        for i in range(len(self.frame_idx_list)):\n"
        "            frame_idx = self.frame_idx_list[i]\n"
        "            cam_param = self.cam_params[frame_idx]\n"
        "            focal, princpt = cam_param['focal'], cam_param['princpt']\n"
        "\n"
        "            kpt = self.kpts[frame_idx]\n"
        "            kpt_img = kpt[:,:2]\n"
        "            kpt_valid = (kpt[:,2:] > 0.2).astype(np.float32)\n"
        "            bbox = get_bbox(kpt_img, kpt_valid[:,0])\n"
        "            bbox = set_aspect_ratio(bbox)\n"
        "\n"
        "            t_z = math.sqrt(focal[0]*focal[1]*cfg.body_3d_size*cfg.body_3d_size/(bbox[2]*bbox[3])) # meter\n"
        "            t_x = bbox[0] + bbox[2]/2 # pixel\n"
        "            t_y = bbox[1] + bbox[3]/2 # pixel\n"
        "            t_x = (t_x - princpt[0]) / focal[0] * t_z # meter\n"
        "            t_y = (t_y - princpt[1]) / focal[1] * t_z # meter\n"
        "            t_xyz = torch.FloatTensor([t_x, t_y, t_z]) \n"
        "            self.smplx_params[frame_idx]['trans'] = t_xyz\n"
    )
    trans_replacement = (
        "    def get_body_bbox_init(self):\n"
        "        valid = {}\n"
        "        for frame_idx in self.frame_idx_list:\n"
        "            kpt = self.kpts[frame_idx]\n"
        "            kpt_img = kpt[:,:2]\n"
        "            kpt_valid = (kpt[:,2:] > 0.2).astype(np.float32)\n"
        "            if int(np.sum(kpt_valid[:,0])) < 2:\n"
        "                continue\n"
        "            bbox = set_aspect_ratio(get_bbox(kpt_img, kpt_valid[:,0]))\n"
        "            if not np.all(np.isfinite(bbox)) or float(bbox[2]) <= 1e-6 or float(bbox[3]) <= 1e-6:\n"
        "                continue\n"
        "            valid[frame_idx] = bbox.astype(np.float32)\n"
        "        if not valid:\n"
        "            raise RuntimeError('BodyRig ExAvatar translation init has no valid >0.2 body bbox seeds')\n"
        "\n"
        "        valid_indices = sorted(valid)\n"
        "        resolved = {}\n"
        "        for frame_idx in self.frame_idx_list:\n"
        "            if frame_idx in valid:\n"
        "                resolved[frame_idx] = valid[frame_idx].copy()\n"
        "                continue\n"
        "            left = [x for x in valid_indices if x < frame_idx]\n"
        "            right = [x for x in valid_indices if x > frame_idx]\n"
        "            left_idx = left[-1] if left else None\n"
        "            right_idx = right[0] if right else None\n"
        "            if left_idx is not None and right_idx is not None:\n"
        "                alpha = float(frame_idx - left_idx) / float(right_idx - left_idx)\n"
        "                bbox = valid[left_idx] * (1.0 - alpha) + valid[right_idx] * alpha\n"
        "                mode = 'interpolated'\n"
        "            elif left_idx is not None:\n"
        "                bbox = valid[left_idx].copy()\n"
        "                mode = 'previous'\n"
        "            else:\n"
        "                bbox = valid[right_idx].copy()\n"
        "                mode = 'next'\n"
        "            resolved[frame_idx] = bbox.astype(np.float32)\n"
        "            print('BodyRig ExAvatar body bbox fallback: {} for frame {}'.format(mode, frame_idx))\n"
        "        return resolved\n"
        "\n"
        "    def get_smplx_trans_init(self):\n"
        "        for i in range(len(self.frame_idx_list)):\n"
        "            frame_idx = self.frame_idx_list[i]\n"
        "            cam_param = self.cam_params[frame_idx]\n"
        "            focal, princpt = cam_param['focal'], cam_param['princpt']\n"
        "            bbox = self.body_bboxes[frame_idx]\n"
        "\n"
        "            t_z = math.sqrt(focal[0]*focal[1]*cfg.body_3d_size*cfg.body_3d_size/(bbox[2]*bbox[3])) # meter\n"
        "            t_x = bbox[0] + bbox[2]/2 # pixel\n"
        "            t_y = bbox[1] + bbox[3]/2 # pixel\n"
        "            t_x = (t_x - princpt[0]) / focal[0] * t_z # meter\n"
        "            t_y = (t_y - princpt[1]) / focal[1] * t_z # meter\n"
        "            t_xyz = torch.FloatTensor([t_x, t_y, t_z]) \n"
        "            self.smplx_params[frame_idx]['trans'] = t_xyz\n"
    )

    item_marker = (
        "        img_height, img_width = img_orig.shape[0], img_orig.shape[1]\n"
        "        bbox = get_bbox(kpt_img, kpt_valid[:,0])\n"
        "        bbox = set_aspect_ratio(bbox)\n"
        "        if np.sum(kpt_valid[smpl_x.kpt['part_idx']['face'],0]) == 0:\n"
        "            self.flame_params[frame_idx]['is_valid'] = False\n"
        "            bbox_face = np.array([0,0,1,1], dtype=np.float32)\n"
        "        else:\n"
        "            bbox_face = get_bbox(kpt_img[smpl_x.kpt['part_idx']['face'],:], kpt_valid[smpl_x.kpt['part_idx']['face'],0])\n"
        "        bbox_face = set_aspect_ratio(bbox_face)\n"
    )
    item_replacement = (
        "        img_height, img_width = img_orig.shape[0], img_orig.shape[1]\n"
        "        bbox = self.body_bboxes[frame_idx].copy()\n"
        "        face_valid = kpt_valid[smpl_x.kpt['part_idx']['face'],0]\n"
        "        if int(np.sum(face_valid)) < 2:\n"
        "            self.flame_params[frame_idx]['is_valid'] = False\n"
        "            bbox_face = np.array([0,0,1,1], dtype=np.float32)\n"
        "        else:\n"
        "            bbox_face = get_bbox(kpt_img[smpl_x.kpt['part_idx']['face'],:], face_valid)\n"
        "            bbox_face = set_aspect_ratio(bbox_face)\n"
        "            if not np.all(np.isfinite(bbox_face)) or float(bbox_face[2]) <= 1e-6 or float(bbox_face[3]) <= 1e-6:\n"
        "                self.flame_params[frame_idx]['is_valid'] = False\n"
        "                bbox_face = np.array([0,0,1,1], dtype=np.float32)\n"
        "        bbox_face = set_aspect_ratio(bbox_face)\n"
    )

    if raw.count(init_marker) != 1 or raw.count(trans_marker) != 1 or raw.count(item_marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar Custom dataset bbox markers changed")
    patched = raw.replace(init_marker, init_replacement, 1)
    patched = patched.replace(trans_marker, trans_replacement, 1)
    patched = patched.replace(item_marker, item_replacement, 1)
    source.write_text(patched, encoding="utf-8")
    return {
        "destination": source.as_posix(),
        "source_sha256": before_sha,
        "replaced_sha256": before_sha,
        "patched_sha256": _file_sha(source),
    }


def _patch_fitting_edge_length_loss(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PhotorealExAvatarWorkspaceError(
            f"pinned ExAvatar fitting loss source missing or unsafe: {path}"
        )
    raw = path.read_text(encoding="utf-8")
    marker = (
        "        d1_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,1],:])**2,2,keepdim=True))\n"
        "        d2_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True))\n"
        "        d3_out = torch.sqrt(torch.sum((coord_out[:,face[:,1],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True))\n"
        "\n"
        "        d1_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,1],:])**2,2,keepdim=True))\n"
        "        d2_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True))\n"
        "        d3_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,1],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True))\n"
    )
    replacement = (
        "        bodyrig_edge_eps = 1e-12\n"
        "        d1_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,1],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
        "        d2_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
        "        d3_out = torch.sqrt(torch.sum((coord_out[:,face[:,1],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
        "\n"
        "        d1_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,1],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
        "        d2_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
        "        d3_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,1],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True) + bodyrig_edge_eps)\n"
    )
    if raw.count(marker) != 1:
        raise PhotorealExAvatarWorkspaceError(
            "pinned ExAvatar fitting EdgeLengthLoss marker changed"
        )
    before = _file_sha(path)
    path.write_text(raw.replace(marker, replacement, 1), encoding="utf-8")
    return {
        "destination": path.as_posix(),
        "source_sha256": before,
        "replaced_sha256": before,
        "patched_sha256": _file_sha(path),
    }


def _copy_hand4whole_with_pinned_keypoint_bbox(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar Hand4Whole patch source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    replaced_sha = _file_sha(destination) if destination.is_file() else None
    raw = source.read_text(encoding="utf-8")
    detector_import_markers = (
        "from torchvision import transforms as T\n",
        "from torchvision.models.detection import fasterrcnn_resnet50_fpn\n",
    )
    detector_helper_marker = (
        "def get_one_box(det_output):\n"
        "    max_score = 0\n"
        "    max_bbox = None\n"
        "\n"
        "    for i in range(det_output['boxes'].shape[0]):\n"
        "        bbox = det_output['boxes'][i]\n"
        "        score = det_output['scores'][i]\n"
        "        if float(score) > max_score:\n"
        "            max_bbox = [float(x) for x in bbox]\n"
        "            max_score = score\n"
        "\n"
        "    return max_bbox\n"
    )
    marker = (
        "    # prepare bbox\n"
        "    det_model = fasterrcnn_resnet50_fpn(pretrained=True).cuda().eval()\n"
        "    det_transform = T.Compose([T.ToTensor()])\n"
        "    det_input = det_transform(original_img).cuda()\n"
        "    det_output = det_model([det_input])[0]\n"
        "    bbox = get_one_box(det_output) # xyxy\n"
        "    if bbox is None:\n"
        "        continue\n"
        "    bbox = [bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1]] # xywh\n"
        "    bbox = process_bbox(bbox, original_img_width, original_img_height)\n"
    )
    replacement = (
        "    # BodyRig: derive the Hand4Whole crop from the already-pinned RTMPose whole-body keypoints.\n"
        "    # This removes torchvision's implicit pretrained Faster R-CNN download and per-frame model init.\n"
        "    kpt_path = osp.join(root_path, 'keypoints_whole_body', str(frame_idx) + '.json')\n"
        "    if not osp.isfile(kpt_path):\n"
        "        raise RuntimeError('BodyRig whole-body keypoints missing for frame {}'.format(frame_idx))\n"
        "    with open(kpt_path) as f:\n"
        "        bodyrig_kpt = np.array(json.load(f), dtype=np.float32)\n"
        "    if bodyrig_kpt.ndim != 2 or bodyrig_kpt.shape[0] < 23 or bodyrig_kpt.shape[1] < 3:\n"
        "        raise RuntimeError('BodyRig whole-body keypoints invalid for frame {}'.format(frame_idx))\n"
        "    bodyrig_person = bodyrig_kpt[:23]\n"
        "    bodyrig_valid = bodyrig_person[:,2] > 0.5\n"
        "    bodyrig_confidence_mode = 'strong'\n"
        "    if int(bodyrig_valid.sum()) < 5:\n"
        "        bodyrig_valid = bodyrig_person[:,2] > 0.2\n"
        "        bodyrig_confidence_mode = 'weak'\n"
        "    bodyrig_candidate_bbox = None\n"
        "    if int(bodyrig_valid.sum()) >= 5:\n"
        "        bodyrig_xy = bodyrig_person[bodyrig_valid,:2]\n"
        "        bodyrig_min = bodyrig_xy.min(axis=0)\n"
        "        bodyrig_max = bodyrig_xy.max(axis=0)\n"
        "        bodyrig_candidate_bbox = [float(bodyrig_min[0]), float(bodyrig_min[1]), float(bodyrig_max[0]-bodyrig_min[0]), float(bodyrig_max[1]-bodyrig_min[1])]\n"
        "        bodyrig_candidate_bbox = process_bbox(bodyrig_candidate_bbox, original_img_width, original_img_height)\n"
        "    if bodyrig_candidate_bbox is not None:\n"
        "        bbox = bodyrig_candidate_bbox\n"
        "        if bodyrig_confidence_mode == 'weak':\n"
        "            print('BodyRig Hand4Whole crop: weak RTMPose fallback for frame {}'.format(frame_idx))\n"
        "    elif bbox is not None:\n"
        "        print('BodyRig Hand4Whole crop: reuse previous valid bbox for frame {}'.format(frame_idx))\n"
        "    else:\n"
        "        print('BodyRig Hand4Whole crop: full-frame bootstrap fallback for frame {}'.format(frame_idx))\n"
        "        bbox = process_bbox([0.0, 0.0, float(original_img_width - 1), float(original_img_height - 1)], original_img_width, original_img_height)\n"
        "        if bbox is None:\n"
        "            raise RuntimeError('BodyRig full-frame Hand4Whole fallback bbox invalid for frame {}'.format(frame_idx))\n"
    )
    if (
        raw.count(marker) != 1
        or raw.count(detector_helper_marker) != 1
        or any(raw.count(item) != 1 for item in detector_import_markers)
    ):
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar Hand4Whole detector marker changed")
    patched = raw
    for item in detector_import_markers:
        patched = patched.replace(item, "", 1)
    patched = patched.replace(detector_helper_marker, "", 1)
    patched = patched.replace(marker, replacement, 1)
    destination.write_text(patched, encoding="utf-8")
    return {
        "destination": destination.as_posix(),
        "source_sha256": _file_sha(source),
        "replaced_sha256": replaced_sha,
        "patched_sha256": _file_sha(destination),
    }


def _patch_hand4whole_inference_only_human_models(root: Path) -> list[dict[str, Any]]:
    human_models = root / "common" / "utils" / "human_models.py"
    preprocessing = root / "common" / "utils" / "preprocessing.py"
    if not human_models.is_file() or not preprocessing.is_file():
        raise PhotorealExAvatarWorkspaceError("pinned Hand4Whole human-model sources are missing")

    human_raw = human_models.read_text(encoding="utf-8")
    human_marker = "smpl_x = SMPLX()\nsmpl = SMPL()\n"
    if human_raw.count(human_marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned Hand4Whole SMPL initialization marker changed")
    human_before = _file_sha(human_models)
    human_models.write_text(
        human_raw.replace(
            human_marker,
            "smpl_x = SMPLX()\n# BodyRig pinned inference path intentionally does not instantiate classic SMPL.\n",
            1,
        ),
        encoding="utf-8",
    )

    prep_raw = preprocessing.read_text(encoding="utf-8")
    prep_marker = "from utils.human_models import smpl_x, smpl\n"
    if prep_raw.count(prep_marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned Hand4Whole preprocessing SMPL import marker changed")
    prep_before = _file_sha(preprocessing)
    preprocessing.write_text(
        prep_raw.replace(prep_marker, "from utils.human_models import smpl_x\n", 1),
        encoding="utf-8",
    )

    return [
        {
            "destination": human_models.as_posix(),
            "source_sha256": human_before,
            "replaced_sha256": human_before,
            "patched_sha256": _file_sha(human_models),
        },
        {
            "destination": preprocessing.as_posix(),
            "source_sha256": prep_before,
            "replaced_sha256": prep_before,
            "patched_sha256": _file_sha(preprocessing),
        },
    ]


def _relativize_injected_patch_destinations(
    records: list[dict[str, Any]],
    *,
    workspace_root: Path,
) -> None:
    root = workspace_root.resolve()
    for record in records:
        destination = Path(str(record.get("destination") or "")).resolve()
        try:
            relative_destination = destination.relative_to(root)
        except ValueError as exc:
            raise PhotorealExAvatarWorkspaceError(
                f"injected ExAvatar patch destination escapes workspace staging root: {destination}"
            ) from exc
        record["destination"] = relative_destination.as_posix()


def _patch_avatar_checkpoint_save(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PhotorealExAvatarWorkspaceError("ExAvatar avatar common/base.py is missing")
    raw = path.read_text(encoding="utf-8")
    marker = (
        "    def save_model(self, state, epoch):\n"
        "        file_path = osp.join(cfg.model_dir,'snapshot_{}.pth'.format(str(epoch)))\n"
        "        torch.save(state, file_path)\n"
        "        self.logger.info(\"Write snapshot into {}\".format(file_path))\n"
    )
    replacement = (
        "    def save_model(self, state, epoch):\n"
        "        file_path = osp.join(cfg.model_dir,'snapshot_{}.pth'.format(str(epoch)))\n"
        "        temp_path = file_path + '.bodyrig-tmp'\n"
        "        if osp.exists(temp_path):\n"
        "            os.remove(temp_path)\n"
        "        torch.save(state, temp_path)\n"
        "        os.replace(temp_path, file_path)\n"
        "        self.logger.info(\"Write snapshot into {}\".format(file_path))\n"
    )
    if raw.count(marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar checkpoint save marker changed")
    before = _file_sha(path)
    patched = raw.replace(marker, replacement, 1)
    path.write_text(patched, encoding="utf-8")
    after = _file_sha(path)
    return {
        "destination": path.as_posix(),
        "source_sha256": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        "replaced_sha256": before,
        "patched_sha256": after,
    }


def _patch_avatar_config(path: Path, *, smplx_gender: str) -> dict[str, Any]:
    if not path.is_file():
        raise PhotorealExAvatarWorkspaceError("ExAvatar avatar config.py is missing")
    raw = path.read_text(encoding="utf-8")
    dataset_marker = "    dataset = 'NeuMan' # Custom, NeuMan"
    gender_marker = "    smplx_gender = 'male' # only use male version as female version is not very good"
    if raw.count(dataset_marker) != 1 or raw.count(gender_marker) != 1:
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar avatar config markers changed")
    before = _file_sha(path)
    patched = raw.replace(dataset_marker, "    dataset = 'Custom' # BodyRig benchmark patch: explicit Custom dataset", 1)
    patched = patched.replace(
        gender_marker,
        f"    smplx_gender = '{smplx_gender}' # BodyRig benchmark patch: explicit geometry prior",
        1,
    )
    path.write_text(patched, encoding="utf-8")
    return {
        "relative_path": "avatar/main/config.py",
        "before_sha256": before,
        "after_sha256": _file_sha(path),
        "dataset": "Custom",
        "smplx_gender": smplx_gender,
    }


def _verify_fitting_config(path: Path) -> str:
    if not path.is_file():
        raise PhotorealExAvatarWorkspaceError("ExAvatar fitting config.py is missing")
    raw = path.read_text(encoding="utf-8")
    if "    dataset = 'Custom' # 'NeuMan', 'Custom', 'XHumans'" not in raw:
        raise PhotorealExAvatarWorkspaceError("pinned ExAvatar fitting config is no longer Custom")
    return _file_sha(path)


def _dependency_root_still_clean(dependency_root: Path) -> bool:
    for name, _url, commit in REPOSITORIES:
        path = dependency_root / PUBLIC_TOOL_LAYOUT[name]
        if _git(path, "rev-parse", "HEAD").lower() != commit:
            return False
        if _git(path, "status", "--porcelain") != "":
            return False
    return True


def build_exavatar_workspace(
    *,
    materialized_dataset_dir: str | Path,
    materialization_receipt_path: str | Path,
    strict_preflight_path: str | Path,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    workspace_root: str | Path,
    smplx_gender: str,
) -> dict[str, Any]:
    gender = str(smplx_gender or "").strip().lower()
    if gender not in {"female", "male", "neutral"}:
        raise PhotorealExAvatarWorkspaceError("smplx_gender must be explicitly female, male or neutral")
    dataset_dir = Path(materialized_dataset_dir).expanduser().resolve()
    dependency_dir = Path(dependency_root).expanduser().resolve()
    assets_dir = Path(asset_root).expanduser().resolve()
    reference_dir = Path(reference_model_root).expanduser().resolve()
    root = Path(workspace_root).expanduser().resolve()
    if root.exists():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar workspace already exists: {root}")
    if not dataset_dir.is_dir() or not dependency_dir.is_dir() or not assets_dir.is_dir() or not reference_dir.is_dir():
        raise PhotorealExAvatarWorkspaceError("ExAvatar workspace input root is missing")

    materialization = _read_json(materialization_receipt_path, label="ExAvatar materialization receipt")
    preflight = _read_json(strict_preflight_path, label="ExAvatar strict preflight receipt")
    preflight_sha = _validate_preflight(preflight, smplx_gender=gender)
    materialization_sha = _validate_materialization(materialization, dataset_dir)
    asset_records = _preflight_asset_map(preflight, key="assets")
    reference_records = _preflight_asset_map(preflight, key="reference_vision_assets")

    performer_id = str(materialization.get("performer_id") or "").strip()
    subject_id = _safe_subject_id(performer_id)
    stage = root.with_name(f".{root.name}.stage-{os.getpid()}")
    if stage.exists():
        raise PhotorealExAvatarWorkspaceError(f"ExAvatar workspace staging path already exists: {stage}")
    stage.mkdir(parents=True)

    try:
        repos_root = stage / "repos"
        repos_root.mkdir()
        commit_map: dict[str, str] = {}
        for name, repository_url, commit in REPOSITORIES:
            relative = PUBLIC_TOOL_LAYOUT[name]
            source = dependency_dir / relative
            destination = repos_root / relative
            _clone_pinned(source, destination, repository_url, commit)
            commit_map[name] = commit

        exavatar = repos_root / "ExAvatar_RELEASE"
        fitting_tools = exavatar / "fitting" / "tools"
        tool_links = {
            "DECA": repos_root / "DECA",
            "Hand4Whole_RELEASE": repos_root / "Hand4Whole_RELEASE",
            "mmpose": repos_root / "mmpose",
            "segment-anything": repos_root / "segment-anything",
            "Depth-Anything-V2": repos_root / "Depth-Anything-V2",
        }
        for name, target in tool_links.items():
            link = fitting_tools / name
            _link_internal_directory(target, link)

        code_to_copy = fitting_tools / "code_to_copy"
        injected: list[dict[str, Any]] = []
        injected.append(_copy_patch(code_to_copy / "run_deca.py", repos_root / "DECA" / "run_deca.py"))
        injected.append(_copy_patch(code_to_copy / "DECA" / "decalib" / "deca.py", repos_root / "DECA" / "decalib" / "deca.py"))
        injected.append(
            _copy_deca_dataset_with_pinned_face_keypoints(
                code_to_copy / "DECA" / "decalib" / "datasets" / "datasets.py",
                repos_root / "DECA" / "decalib" / "datasets" / "datasets.py",
            )
        )
        injected.append(_copy_patch(code_to_copy / "DECA" / "demos" / "demo_reconstruct.py", repos_root / "DECA" / "demos" / "demo_reconstruct.py"))
        injected.append(
            _copy_hand4whole_with_pinned_keypoint_bbox(
                code_to_copy / "run_hand4whole.py",
                repos_root / "Hand4Whole_RELEASE" / "demo" / "run_hand4whole.py",
            )
        )
        injected.extend(
            _patch_hand4whole_inference_only_human_models(
                repos_root / "Hand4Whole_RELEASE"
            )
        )
        injected.append(_copy_patch(code_to_copy / "mmpose" / "demo" / "topdown_demo_with_mmdet.py", repos_root / "mmpose" / "demo" / "topdown_demo_with_mmdet.py"))
        injected.append(_copy_patch(code_to_copy / "run_mmpose.py", repos_root / "mmpose" / "run_mmpose.py"))
        injected.append(
            _copy_sam_with_temporal_bbox_fallback(
                code_to_copy / "run_sam.py",
                repos_root / "segment-anything" / "run_sam.py",
            )
        )
        injected.append(_copy_patch(code_to_copy / "run_depth_anything.py", repos_root / "Depth-Anything-V2" / "run_depth_anything.py"))
        injected.append(
            _patch_exavatar_custom_dataset_body_bboxes(
                exavatar / "fitting" / "data" / "Custom" / "Custom.py"
            )
        )
        injected.append(
            _patch_fitting_edge_length_loss(
                exavatar / "fitting" / "common" / "nets" / "loss.py"
            )
        )
        injected.append(_patch_avatar_checkpoint_save(exavatar / "avatar" / "common" / "base.py"))
        colmap_dir = fitting_tools / "COLMAP"
        colmap_dir.mkdir(exist_ok=False)
        injected.append(_copy_patch(code_to_copy / "run_colmap.py", colmap_dir / "run_colmap.py"))

        _relativize_injected_patch_destinations(injected, workspace_root=stage)

        linked_assets: list[dict[str, Any]] = []

        def link_asset(relative: str, destination: Path, *, reference: bool = False) -> None:
            records = reference_records if reference else asset_records
            source_root = reference_dir if reference else assets_dir
            source = _verify_asset(source_root, relative, records)
            _link_file(source, destination)
            linked_assets.append(
                {
                    "source_relative_path": relative,
                    "destination": destination.relative_to(stage).as_posix(),
                    "sha256": _file_sha(source),
                    "reference_vision_asset": reference,
                }
            )

        link_asset("deca/deca_model.tar", repos_root / "DECA" / "data" / "deca_model.tar")
        link_asset("deca/FLAME2020/female_model.pkl", repos_root / "DECA" / "data" / "FLAME2020" / "female_model.pkl")
        link_asset("deca/FLAME2020/male_model.pkl", repos_root / "DECA" / "data" / "FLAME2020" / "male_model.pkl")
        link_asset("deca/generic_model.pkl", repos_root / "DECA" / "data" / "generic_model.pkl")
        link_asset("hand4whole/snapshot_6.pth.tar", repos_root / "Hand4Whole_RELEASE" / "demo" / "snapshot_6.pth.tar")
        link_asset("sam/sam_vit_h_4b8939.pth", repos_root / "segment-anything" / "sam_vit_h_4b8939.pth")
        link_asset("depth-anything-v2/depth_anything_v2_vitl.pth", repos_root / "Depth-Anything-V2" / "checkpoints" / "depth_anything_v2_vitl.pth")
        link_asset(
            "weights/rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.pth",
            repos_root / "mmpose" / "dw-ll_ucoco_384.pth",
            reference=True,
        )
        link_asset(
            "weights/rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth",
            repos_root / "mmpose" / "rtmdet_m_8xb32-100e_coco-obj365-person-235e8209.pth",
            reference=True,
        )

        human_root = assets_dir / "human_model_files"
        expected_human_files = [
            relative[len("human_model_files/") :]
            for relative in asset_records
            if relative.startswith("human_model_files/")
        ]
        if len(expected_human_files) < 10:
            raise PhotorealExAvatarWorkspaceError("strict preflight human model asset inventory is unexpectedly small")
        for subpath in sorted(expected_human_files):
            source_relative = f"human_model_files/{subpath}"
            source = _verify_asset(assets_dir, source_relative, asset_records)
            for target_root in (
                exavatar / "fitting" / "common" / "utils" / "human_model_files",
                exavatar / "avatar" / "common" / "utils" / "human_model_files",
            ):
                destination = target_root / subpath
                if subpath == "flame/flame_static_embedding.pkl":
                    staged_sha = _stage_flame_static_embedding(source, destination)
                else:
                    _link_file(source, destination)
                    staged_sha = _file_sha(source)
                linked_assets.append(
                    {
                        "source_relative_path": source_relative,
                        "destination": destination.relative_to(stage).as_posix(),
                        "sha256": staged_sha,
                        "reference_vision_asset": False,
                    }
                )

        sith_uv = _resolve_pinned_sith_uv_template()
        sith_uv_sha = _file_sha(sith_uv)
        for target_root in (
            exavatar / "fitting" / "common" / "utils" / "human_model_files",
            exavatar / "avatar" / "common" / "utils" / "human_model_files",
        ):
            destination = target_root / "smplx" / "smplx_uv" / "smplx_uv.obj"
            if destination.exists() or destination.is_symlink():
                raise PhotorealExAvatarWorkspaceError(
                    f"canonical SMPL-X UV destination already exists: {destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sith_uv, destination)
            if _file_sha(destination) != sith_uv_sha:
                raise PhotorealExAvatarWorkspaceError(
                    "canonical SMPL-X UV template changed during workspace staging"
                )
            linked_assets.append(
                {
                    "source_relative_path": "public/sith/data/smplx_uv.obj",
                    "destination": destination.relative_to(stage).as_posix(),
                    "sha256": sith_uv_sha,
                    "reference_vision_asset": False,
                }
            )

        # Ensure the supplemental strict FLAME files are present in the staged human model tree.
        for _name, relative in STRICT_FLAME_ASSETS:
            subpath = relative[len("human_model_files/") :]
            for target_root in (
                exavatar / "fitting" / "common" / "utils" / "human_model_files",
                exavatar / "avatar" / "common" / "utils" / "human_model_files",
            ):
                if not (target_root / subpath).is_file():
                    raise PhotorealExAvatarWorkspaceError(f"strict FLAME asset not staged: {relative}")

        working_dataset = stage / "dataset" / subject_id
        working_dataset.parent.mkdir(parents=True)
        shutil.copytree(dataset_dir, working_dataset, symlinks=False)
        if (working_dataset / "video.mp4").exists():
            raise PhotorealExAvatarWorkspaceError("workspace dataset unexpectedly contains original video")
        for frame in materialization["frames"]:
            index = int(frame["exavatar_frame_index"])
            staged = working_dataset / "frames" / f"{index}.png"
            if _file_sha(staged) != _sha(frame.get("staged_png_sha256"), label="workspace frame SHA-256"):
                raise PhotorealExAvatarWorkspaceError(f"workspace dataset frame changed during copy: {index}")

        for pipeline in ("fitting", "avatar"):
            data_parent = exavatar / pipeline / "data" / "Custom" / "data"
            data_parent.mkdir(parents=True, exist_ok=True)
            link = data_parent / subject_id
            _link_internal_directory(working_dataset, link)

        fitting_config_sha = _verify_fitting_config(exavatar / "fitting" / "main" / "config.py")
        avatar_patch = _patch_avatar_config(exavatar / "avatar" / "main" / "config.py", smplx_gender=gender)

        if not _dependency_root_still_clean(dependency_dir):
            raise PhotorealExAvatarWorkspaceError("preparing ExAvatar workspace modified pinned dependency root")

        result: dict[str, Any] = {
            "format": WORKSPACE_FORMAT,
            "version": VERSION,
            "performer_id": performer_id,
            "subject_id": subject_id,
            "selected_epoch_id": str(materialization.get("selected_epoch_id") or ""),
            "benchmark_plan_sha256": _sha(materialization.get("benchmark_plan_sha256"), label="benchmark plan SHA-256"),
            "teacher_input_sha256": _sha(materialization.get("teacher_input_sha256"), label="teacher input SHA-256"),
            "materialization_receipt_sha256": materialization_sha,
            "strict_preflight_sha256": preflight_sha,
            "upstream_commit": UPSTREAM_COMMIT,
            "repository_commits": commit_map,
            "smplx_gender": gender,
            "smplx_gender_explicit": True,
            "upstream_default_gender_accepted": False,
            "dataset": "Custom",
            "fitting_config_sha256": fitting_config_sha,
            "avatar_config_patch": avatar_patch,
            "injected_patch_files": injected,
            "linked_assets": linked_assets,
            "frame_count": len(materialization["frames"]),
            "working_dataset_relative_path": f"dataset/{subject_id}",
            "held_out_evaluation_disclosed": False,
            "original_video_copied": False,
            "dependency_root_modified": False,
            "photoreal_acceptance_authority": False,
            "human_visual_acceptance_required": True,
            "build_only": True,
            "runtime_dependency": False,
            "production_activation": False,
        }
        result["workspace_sha256"] = _canonical_digest(result, omit="workspace_sha256")
        receipt_path = stage / "workspace-receipt.json"
        receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

        stage.rename(root)
        return result
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def build_exavatar_workspace_files(
    *,
    materialized_dataset_dir: str | Path,
    materialization_receipt_path: str | Path,
    strict_preflight_path: str | Path,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    workspace_root: str | Path,
    smplx_gender: str,
) -> dict[str, Any]:
    return build_exavatar_workspace(
        materialized_dataset_dir=materialized_dataset_dir,
        materialization_receipt_path=materialization_receipt_path,
        strict_preflight_path=strict_preflight_path,
        dependency_root=dependency_root,
        asset_root=asset_root,
        reference_model_root=reference_model_root,
        workspace_root=workspace_root,
        smplx_gender=smplx_gender,
    )
