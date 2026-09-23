from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


PINNED_UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
PINNED_TEST_EPOCH = 4
REQUEST_FORMAT = "bodyrig-photoreal-p3-device-distillation-request"
CANDIDATE_FORMAT = "bodyrig-photoreal-p3-exavatar-quest2-student-candidate"
VERSION = 1
EXPECTED_SOURCE_KINDS = {
    "teacher-checkpoint",
    "shape-param",
    "face-offset",
    "joint-offset",
    "locator-offset",
}
IDENTITY_FILENAMES = {
    "shape-param": "shape_param.json",
    "face-offset": "face_offset.json",
    "joint-offset": "joint_offset.json",
    "locator-offset": "locator_offset.json",
}
BLOCKERS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
    "teacher-student-fidelity-delta-measurement",
    "p3-distillation-manifest",
)


class Quest2StudentCandidateError(ValueError):
    pass


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Quest2StudentCandidateError(
            "P3 request cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _sha_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise Quest2StudentCandidateError(
            f"required file is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Quest2StudentCandidateError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise Quest2StudentCandidateError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise Quest2StudentCandidateError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise Quest2StudentCandidateError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=64).lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise Quest2StudentCandidateError(f"{label} is invalid")
    return clean


def _relative(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if (
        clean.startswith("/")
        or clean.startswith("../")
        or "/../" in f"/{clean}/"
        or ":" in first
    ):
        raise Quest2StudentCandidateError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative(relative, label=label)
    target = (root / clean).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise Quest2StudentCandidateError(f"{label} escapes its root") from exc
    return clean, target


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise Quest2StudentCandidateError(
            "could not verify pinned ExAvatar repository"
            + (f": {detail}" if detail else "")
        )
    return (completed.stdout or "").strip()


def _validate_request(
    request: Mapping[str, Any],
    *,
    adapter: str,
    revision: str,
    representation: str,
    student_components: str,
) -> None:
    if request.get("format") != REQUEST_FORMAT:
        raise Quest2StudentCandidateError("P3 request format mismatch")
    claimed_request_sha = _sha(
        request.get("p3_device_distillation_request_sha256"),
        label="P3 request SHA-256",
    )
    if _digest(
        request,
        omit="p3_device_distillation_request_sha256",
    ) != claimed_request_sha:
        raise Quest2StudentCandidateError("P3 request digest mismatch")
    if request.get("target_profile", {}).get("target_model") != "quest-2":
        raise Quest2StudentCandidateError(
            "Quest2 student candidate requires target_model=quest-2"
        )
    if request.get("student_representation") != representation:
        raise Quest2StudentCandidateError(
            "student representation differs from P3 request"
        )
    if representation != "skinned-mesh-pbr":
        raise Quest2StudentCandidateError(
            "Quest2 candidate v1 only materializes skinned-mesh-pbr"
        )
    if request.get("adapter") != adapter:
        raise Quest2StudentCandidateError("adapter name differs from P3 request")
    if request.get("adapter_revision") != revision:
        raise Quest2StudentCandidateError(
            "adapter revision differs from P3 request"
        )
    expected_components = request.get("student_components")
    if (
        not isinstance(expected_components, list)
        or student_components != ",".join(str(item) for item in expected_components)
    ):
        raise Quest2StudentCandidateError(
            "student component CLI binding differs from P3 request"
        )
    if request.get("staged_teacher_only") is not True:
        raise Quest2StudentCandidateError(
            "P3 request did not preserve staged-teacher-only authority"
        )
    for field in (
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if request.get(field) is not False:
            raise Quest2StudentCandidateError(
                f"P3 request crossed candidate authority: {field}"
            )


def _verify_workspace(
    root: Path,
    request: Mapping[str, Any],
) -> Path:
    receipt = _read_json(
        root / "workspace-receipt.json",
        label="ExAvatar workspace receipt",
    )
    if receipt.get("format") != "bodyrig-photoreal-exavatar-workspace":
        raise Quest2StudentCandidateError("ExAvatar workspace format mismatch")
    if receipt.get("upstream_commit") != PINNED_UPSTREAM_COMMIT:
        raise Quest2StudentCandidateError("ExAvatar workspace commit mismatch")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
    ):
        if receipt.get(field) != request.get(field):
            raise Quest2StudentCandidateError(
                f"ExAvatar workspace/P3 lineage mismatch: {field}"
            )
    if receipt.get("dataset") != "Custom":
        raise Quest2StudentCandidateError("ExAvatar workspace dataset is not Custom")
    if receipt.get("smplx_gender_explicit") is not True:
        raise Quest2StudentCandidateError(
            "ExAvatar workspace lacks explicit SMPL-X gender authority"
        )
    for field, expected in (
        ("upstream_default_gender_accepted", False),
        ("held_out_evaluation_disclosed", False),
        ("original_video_copied", False),
        ("dependency_root_modified", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise Quest2StudentCandidateError(
                f"ExAvatar workspace authority mismatch: {field}"
            )
    repositories = receipt.get("repository_commits")
    if (
        not isinstance(repositories, Mapping)
        or repositories.get("exavatar") != PINNED_UPSTREAM_COMMIT
    ):
        raise Quest2StudentCandidateError(
            "ExAvatar workspace repository provenance mismatch"
        )
    patch = receipt.get("avatar_config_patch")
    if not isinstance(patch, Mapping):
        raise Quest2StudentCandidateError(
            "ExAvatar workspace config-patch provenance is missing"
        )
    repo = root / "repos" / "ExAvatar_RELEASE"
    if not repo.is_dir() or repo.is_symlink():
        raise Quest2StudentCandidateError("pinned ExAvatar repository is missing")
    if _git(repo, "rev-parse", "HEAD").lower() != PINNED_UPSTREAM_COMMIT:
        raise Quest2StudentCandidateError("ExAvatar repository HEAD drifted")

    config = repo / "avatar" / "main" / "config.py"
    expected_config = _sha(
        patch.get("after_sha256"),
        label="ExAvatar patched config SHA-256",
    )
    if _sha_file(config) != expected_config:
        raise Quest2StudentCandidateError("ExAvatar patched config bytes drifted")

    linked_assets = receipt.get("linked_assets")
    if not isinstance(linked_assets, list) or not linked_assets:
        raise Quest2StudentCandidateError(
            "ExAvatar workspace linked-asset provenance is missing"
        )
    asset_prefix = "repos/ExAvatar_RELEASE/avatar/common/utils/human_model_files/"
    verified_asset_count = 0
    for raw in linked_assets:
        if not isinstance(raw, Mapping):
            raise Quest2StudentCandidateError(
                "ExAvatar workspace linked-asset entry is invalid"
            )
        destination = _relative(
            raw.get("destination"),
            label="ExAvatar linked-asset destination",
        )
        if not destination.startswith(asset_prefix):
            continue
        asset = (root / destination).resolve()
        try:
            asset.relative_to(root.resolve())
        except ValueError as exc:
            raise Quest2StudentCandidateError(
                "ExAvatar linked model asset escapes workspace"
            ) from exc
        expected_asset_sha = _sha(
            raw.get("sha256"),
            label="ExAvatar linked model asset SHA-256",
        )
        if _sha_file(asset) != expected_asset_sha:
            raise Quest2StudentCandidateError(
                f"ExAvatar linked model asset bytes drifted: {destination}"
            )
        verified_asset_count += 1
    if verified_asset_count < 1:
        raise Quest2StudentCandidateError(
            "ExAvatar workspace contains no verified human-model assets"
        )

    protected = (
        "avatar/main/model.py",
        "avatar/common/base.py",
        "avatar/common/nets/module.py",
        "avatar/common/utils/smpl_x.py",
        "avatar/common/utils/smplx/smplx/body_models.py",
        "avatar/common/utils/smplx/smplx/lbs.py",
    )
    if _git(repo, "status", "--porcelain", "--", *protected):
        raise Quest2StudentCandidateError(
            "pinned ExAvatar student runtime code has local modifications"
        )
    return repo


def _verify_staged_teacher(
    request: Mapping[str, Any],
    teacher_root: Path,
) -> dict[str, Path]:
    raw_sources = request.get("staged_teacher_sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != 5:
        raise Quest2StudentCandidateError(
            "P3 staged teacher source universe is incomplete"
        )
    result: dict[str, Path] = {}
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise Quest2StudentCandidateError("P3 staged teacher entry is invalid")
        kind = _text(
            raw.get("kind"),
            label="P3 staged teacher kind",
            maximum=64,
        )
        if kind not in EXPECTED_SOURCE_KINDS or kind in result:
            raise Quest2StudentCandidateError(
                "P3 staged teacher kind universe mismatch"
            )
        root_kind = _text(
            raw.get("root_kind"),
            label="P3 staged teacher root kind",
            maximum=64,
        )
        expected_root_kind = (
            "teacher-output"
            if kind == "teacher-checkpoint"
            else "identity-export"
        )
        if root_kind != expected_root_kind:
            raise Quest2StudentCandidateError(
                f"P3 staged {kind} root-kind mismatch"
            )
        relative, path = _safe_child(
            teacher_root,
            raw.get("relative_path"),
            label=f"P3 staged {kind} path",
        )
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise Quest2StudentCandidateError(
                f"P3 staged {kind} size/path mismatch: {relative}"
            )
        if _sha_file(path) != _sha(
            raw.get("sha256"),
            label=f"P3 staged {kind} SHA-256",
        ):
            raise Quest2StudentCandidateError(
                f"P3 staged {kind} bytes differ from request"
            )
        result[kind] = path
    if set(result) != EXPECTED_SOURCE_KINDS:
        raise Quest2StudentCandidateError(
            "P3 staged teacher source universe mismatch"
        )
    actual = {
        path.relative_to(teacher_root).as_posix()
        for path in teacher_root.rglob("*")
        if path.is_file()
    }
    expected = {
        _relative(
            raw["relative_path"],
            label="P3 staged teacher relative path",
        )
        for raw in raw_sources
    }
    if actual != expected:
        raise Quest2StudentCandidateError(
            "P3 staged teacher filesystem universe differs from request"
        )
    return result


def _copy_code(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise Quest2StudentCandidateError(f"required code tree missing: {source}")
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "neutral_pose",
            "*.mp4",
            "*.log",
        ),
    )


def _prepare_exavatar_stage(
    *,
    stage: Path,
    repo: Path,
    sources: Mapping[str, Path],
    subject: str,
) -> Path:
    avatar = stage / "avatar"
    _copy_code(repo / "avatar" / "main", avatar / "main")
    _copy_code(repo / "avatar" / "common", avatar / "common")

    custom = repo / "avatar" / "data" / "Custom"
    if not custom.is_dir() or custom.is_symlink():
        raise Quest2StudentCandidateError("ExAvatar Custom dataset code is missing")
    shutil.copytree(
        custom,
        avatar / "data" / "Custom",
        symlinks=True,
        ignore=shutil.ignore_patterns(
            "data",
            "__pycache__",
            "*.pyc",
            "*.pyo",
        ),
    )

    identity = avatar / "data" / "Custom" / "data" / subject / "smplx_optimized"
    identity.mkdir(parents=True)
    for kind, filename in IDENTITY_FILENAMES.items():
        shutil.copy2(sources[kind], identity / filename)

    checkpoint = avatar / "output" / "model_dump" / subject / "snapshot_4.pth"
    checkpoint.parent.mkdir(parents=True)
    shutil.copy2(sources["teacher-checkpoint"], checkpoint)
    return avatar / "main"


def _load_zero_pose_teacher(
    *,
    main_dir: Path,
    subject: str,
) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise Quest2StudentCandidateError(
            f"numpy/torch are required for Quest2 student materialization: {exc}"
        ) from exc
    if not torch.cuda.is_available():
        raise Quest2StudentCandidateError(
            "Quest2 ExAvatar student materialization requires CUDA"
        )

    common_dir = main_dir.parent / "common"
    inserted = [str(main_dir), str(common_dir)]
    old_cwd = Path.cwd()
    for value in reversed(inserted):
        if value not in sys.path:
            sys.path.insert(0, value)
    os.chdir(main_dir)
    try:
        from base import Tester
        from config import cfg
        from utils.smpl_x import smpl_x

        cfg.set_args(subject)

        identity_root = (
            main_dir.parent
            / "data"
            / "Custom"
            / "data"
            / subject
            / "smplx_optimized"
        )
        with (identity_root / "shape_param.json").open("r", encoding="utf-8") as stream:
            shape_param = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "face_offset.json").open("r", encoding="utf-8") as stream:
            face_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "joint_offset.json").open("r", encoding="utf-8") as stream:
            joint_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "locator_offset.json").open("r", encoding="utf-8") as stream:
            locator_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        smpl_x.set_id_info(
            shape_param,
            face_offset,
            joint_offset,
            locator_offset,
        )

        tester = Tester(str(PINNED_TEST_EPOCH))
        tester.smplx_params = None
        tester._make_model()
        human = tester.model.module.human_gaussian

        zero3 = torch.zeros((3,), dtype=torch.float32, device="cuda")
        smplx_param = {
            "root_pose": zero3,
            "body_pose": torch.zeros(
                ((len(smpl_x.joint_part["body"]) - 1) * 3,),
                dtype=torch.float32,
                device="cuda",
            ),
            "jaw_pose": zero3.clone(),
            "leye_pose": zero3.clone(),
            "reye_pose": zero3.clone(),
            "lhand_pose": torch.zeros(
                (len(smpl_x.joint_part["lhand"]) * 3,),
                dtype=torch.float32,
                device="cuda",
            ),
            "rhand_pose": torch.zeros(
                (len(smpl_x.joint_part["rhand"]) * 3,),
                dtype=torch.float32,
                device="cuda",
            ),
            "expr": torch.zeros(
                (smpl_x.expr_param_dim,),
                dtype=torch.float32,
                device="cuda",
            ),
            "trans": zero3.clone(),
        }
        cam = {
            "R": torch.eye(3, dtype=torch.float32, device="cuda"),
            "t": zero3.clone(),
            "focal": torch.tensor(
                (1500.0, 1500.0),
                dtype=torch.float32,
                device="cuda",
            ),
            "princpt": torch.tensor(
                (512.0, 512.0),
                dtype=torch.float32,
                device="cuda",
            ),
        }

        with torch.no_grad():
            _base_teacher, refined_teacher, _offsets, _neutral = human(
                smplx_param,
                cam,
                is_world_coord=True,
            )
            zero_upsampled, zero_mesh, zero_joints = human.get_zero_pose_human(
                return_mesh=True
            )

        weights = human.skinning_weight.float()
        top_weight, top_joint = torch.topk(weights, k=4, dim=1)
        totals = top_weight.sum(dim=1, keepdim=True)
        if bool(torch.any(totals <= 1e-8).item()):
            raise Quest2StudentCandidateError(
                "ExAvatar SMPL-X skinning contains empty influence sets"
            )
        top_weight = top_weight / totals

        parents = [
            int(value)
            for value in human.smplx_layer.parents.detach().cpu().tolist()
        ]
        faces = np.asarray(smpl_x.face_orig, dtype=np.int64)
        first_subdivision_faces = np.asarray(
            smpl_x.subdivider_list[0]._subdivided_faces.detach().cpu().numpy(),
            dtype=np.int64,
        )
        subdivider_source_face_count = int(len(smpl_x.face))
        if zero_mesh.shape != (smpl_x.vertex_num, 3):
            raise Quest2StudentCandidateError(
                "ExAvatar zero-pose mesh topology is unexpected"
            )
        if zero_joints.shape[0] < smpl_x.joint_num:
            raise Quest2StudentCandidateError(
                "ExAvatar zero-pose joint universe is incomplete"
            )

        teacher_xyz = refined_teacher["mean_3d"].detach().cpu().numpy()
        teacher_rgb = refined_teacher["rgb"].detach().cpu().numpy()
        if teacher_xyz.ndim != 2 or teacher_xyz.shape[1] != 3:
            raise Quest2StudentCandidateError(
                "ExAvatar refined teacher geometry is invalid"
            )
        if teacher_xyz.shape[0] < smpl_x.vertex_num:
            raise Quest2StudentCandidateError(
                "ExAvatar refined teacher geometry is smaller than the SMPL-X surface"
            )
        if (
            weights.ndim != 2
            or weights.shape[0] != teacher_xyz.shape[0]
            or weights.shape[1] != smpl_x.joint_num
        ):
            raise Quest2StudentCandidateError(
                "ExAvatar refined skinning weights do not match the Gaussian surface"
            )
        zero_upsampled_np = zero_upsampled.detach().cpu().numpy()
        if zero_upsampled_np.shape != teacher_xyz.shape:
            raise Quest2StudentCandidateError(
                "ExAvatar zero/refined upsampled geometry universes differ"
            )
        if (
            first_subdivision_faces.ndim != 2
            or first_subdivision_faces.shape[1] != 3
            or first_subdivision_faces.shape[0] != subdivider_source_face_count * 4
        ):
            raise Quest2StudentCandidateError(
                "ExAvatar first-subdivision topology is invalid"
            )

        # Pinned ExAvatar keeps the original low-resolution SMPL-X vertices as
        # the leading prefix of its upsampled Gaussian surface. Keep the exact
        # topology/LBS contract, but drive the runtime body surface from the
        # learned source-derived Gaussian positions instead of the naked
        # zero-pose SMPL-X template.
        refined_mesh = np.asarray(
            teacher_xyz[: smpl_x.vertex_num],
            dtype=np.float32,
        )
        if refined_mesh.shape != tuple(zero_mesh.shape):
            raise Quest2StudentCandidateError(
                "ExAvatar refined low-resolution surface topology is unexpected"
            )
        if not np.all(np.isfinite(refined_mesh)):
            raise Quest2StudentCandidateError(
                "ExAvatar refined low-resolution surface is non-finite"
            )
        canonical_mesh = zero_mesh.detach().cpu().numpy()
        geometry_delta = np.linalg.norm(
            refined_mesh - canonical_mesh,
            axis=1,
        )
        if (
            geometry_delta.size != smpl_x.vertex_num
            or not np.all(np.isfinite(geometry_delta))
            or np.array_equal(refined_mesh, canonical_mesh)
        ):
            raise Quest2StudentCandidateError(
                "ExAvatar refined source geometry collapsed to the canonical SMPL-X base"
            )

        return {
            "np": np,
            "torch": torch,
            "device": torch.device("cuda"),
            "teacher_xyz": teacher_xyz,
            "teacher_rgb": teacher_rgb,
            "zero_mesh": zero_mesh.detach().cpu().numpy(),
            "zero_upsampled": zero_upsampled_np,
            "refined_mesh": refined_mesh,
            "first_subdivision_faces": first_subdivision_faces,
            "subdivider_source_face_count": subdivider_source_face_count,
            "refined_geometry_offset_mean": float(np.mean(geometry_delta)),
            "refined_geometry_offset_p95": float(np.percentile(geometry_delta, 95.0)),
            "refined_geometry_offset_max": float(np.max(geometry_delta)),
            "zero_joints": zero_joints[: smpl_x.joint_num].detach().cpu().numpy(),
            "joints4": top_joint.detach().cpu().numpy(),
            "weights4": top_weight.detach().cpu().numpy(),
            "parents": parents,
            "faces": faces,
            "joint_names": tuple(smpl_x.joints_name),
        }
    finally:
        os.chdir(old_cwd)


def _canonical_exavatar_joint_name(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise Quest2StudentCandidateError("ExAvatar joint name is empty")
    prefixes = {
        "L_": "left_",
        "R_": "right_",
    }
    for prefix, replacement in prefixes.items():
        if clean.startswith(prefix):
            clean = replacement + clean[len(prefix):]
            break
    clean = clean.lower()
    parts = clean.split("_")
    if len(parts) >= 2 and parts[-1].isdigit():
        clean = "_".join(parts[:-1]) + parts[-1]
    return clean


def _validate_joint_semantics(
    exavatar_names: tuple[str, ...],
    bodyrig_names: tuple[str, ...],
) -> None:
    normalized = tuple(
        _canonical_exavatar_joint_name(name)
        for name in exavatar_names
    )
    if normalized != bodyrig_names:
        raise Quest2StudentCandidateError(
            "ExAvatar/BodyRig SMPL-X joint semantic universe differs"
        )



def _first_subdivision_uv_binding(
    *,
    texcoords: list[tuple[float, float]],
    bound_faces: list[list[tuple[int, int]]],
    subdivided_faces: Any,
    subdivider_source_face_count: int,
) -> tuple[list[tuple[float, float]], list[list[tuple[int, int]]], int]:
    base_face_count = len(bound_faces)
    if (
        base_face_count < 1
        or subdivider_source_face_count < base_face_count
        or len(subdivided_faces) != subdivider_source_face_count * 4
    ):
        raise Quest2StudentCandidateError(
            "ExAvatar first-subdivision face universe is inconsistent"
        )

    geometry_blocks: list[list[list[int]]] = []
    for block in range(4):
        start = block * subdivider_source_face_count
        block_faces = [
            [int(value) for value in subdivided_faces[start + index]]
            for index in range(base_face_count)
        ]
        if any(len(face) != 3 for face in block_faces):
            raise Quest2StudentCandidateError(
                "ExAvatar first-subdivision face width is invalid"
            )
        geometry_blocks.append(block_faces)

    refined_texcoords = [
        (float(value[0]), float(value[1]))
        for value in texcoords
    ]
    midpoint_by_edge: dict[tuple[int, int], int] = {}

    def midpoint(left: int, right: int) -> int:
        if (
            left < 0
            or right < 0
            or left >= len(texcoords)
            or right >= len(texcoords)
        ):
            raise Quest2StudentCandidateError(
                "canonical UV subdivision edge escapes source UVs"
            )
        key = (left, right) if left < right else (right, left)
        existing = midpoint_by_edge.get(key)
        if existing is not None:
            return existing
        lu, lv = refined_texcoords[left]
        ru, rv = refined_texcoords[right]
        index = len(refined_texcoords)
        refined_texcoords.append(((lu + ru) * 0.5, (lv + rv) * 0.5))
        midpoint_by_edge[key] = index
        return index

    texture_blocks: list[list[list[int]]] = [[], [], [], []]
    for face_index, base_face in enumerate(bound_faces):
        if len(base_face) != 3:
            raise Quest2StudentCandidateError(
                "canonical base face width is invalid"
            )
        geometry = [int(item[0]) for item in base_face]
        texture = [int(item[1]) for item in base_face]
        a, b, c = geometry
        ua, ub, uc = texture
        g0 = geometry_blocks[0][face_index]
        g1 = geometry_blocks[1][face_index]
        g2 = geometry_blocks[2][face_index]
        g3 = geometry_blocks[3][face_index]
        if g0[0] != a or g1[0] != b or g2[0] != c:
            raise Quest2StudentCandidateError(
                "ExAvatar subdivision no longer preserves source face ordering"
            )
        mab = g0[1]
        mac = g0[2]
        mbc = g1[1]
        if (
            g1[2] != mab
            or g2[1] != mac
            or g2[2] != mbc
            or g3 != [mbc, mac, mab]
        ):
            raise Quest2StudentCandidateError(
                "ExAvatar subdivision edge topology is non-canonical"
            )

        umab = midpoint(ua, ub)
        umac = midpoint(ua, uc)
        umbc = midpoint(ub, uc)
        texture_blocks[0].append([ua, umab, umac])
        texture_blocks[1].append([ub, umbc, umab])
        texture_blocks[2].append([uc, umac, umbc])
        texture_blocks[3].append([umbc, umac, umab])

    result: list[list[tuple[int, int]]] = []
    source_vertices: set[int] = set()
    for block in range(4):
        for geometry, texture in zip(
            geometry_blocks[block],
            texture_blocks[block],
            strict=True,
        ):
            result.append(
                [
                    (geometry[corner], texture[corner])
                    for corner in range(3)
                ]
            )
            source_vertices.update(geometry)

    if len(result) != base_face_count * 4 or len(source_vertices) <= 10475:
        raise Quest2StudentCandidateError(
            "Quest2 refined subdivision did not increase body geometry density"
        )
    if max(source_vertices) > 65535:
        raise Quest2StudentCandidateError(
            "Quest2 refined subdivision exceeds uint16 source-vertex authority"
        )
    return refined_texcoords, result, len(source_vertices)


def _patch_student_vrm(
    avatar: bytes,
    *,
    teacher_checkpoint_sha256: str,
    appearance_metrics: Mapping[str, Any],
) -> bytes:
    from bodyrig.bridges.sith_pbr_material import (
        PbrMaterialError,
        _read_glb,
        _write_glb,
    )

    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise Quest2StudentCandidateError(
            f"generated Quest2 VRM is invalid: {exc}"
        ) from exc
    document.setdefault("asset", {})["generator"] = (
        "BodyRig ExAvatar Quest2 student candidate/1"
    )
    extras = document.setdefault("extras", {}).setdefault("bodyrig", {})
    extras["placeholder"] = False
    extras["sourceDerivedVisualIdentity"] = True
    extras["studentCandidate"] = True
    extras["studentRepresentation"] = "skinned-mesh-pbr"
    extras["teacherCheckpointSha256"] = teacher_checkpoint_sha256
    extras["appearanceTransfer"] = dict(appearance_metrics)
    extras["fitter"] = {
        "adapter": "exavatar-quest2-student-candidate",
        "revision": "1",
    }
    extras["rigTransfer"] = {
        "method": "direct-exavatar-smplx-lbs",
        "nearestDistanceP95": 0.0,
        "nearestDistanceMax": 0.0,
    }
    extras["runtimeAcceptanceAuthority"] = False
    extras["photorealAcceptanceAuthority"] = False
    extras["productionActivation"] = False
    return _write_glb(document, binary)


def _materialize_candidate(
    *,
    request: Mapping[str, Any],
    main_dir: Path,
    canonical_uv_template: Path,
    output: Path,
    checkpoint_sha256: str,
) -> dict[str, Any]:
    from bodyrig.bridges.sith_smplx_vrm_fitter import (
        SMPLX_JOINT_NAMES,
        _build_vrm,
    )
    from bodyrig.photoreal_p3_teacher_point_bake import (
        bake_exavatar_teacher_points_to_canonical_smplx,
    )

    state = _load_zero_pose_teacher(
        main_dir=main_dir,
        subject="bodyrig-p3-student",
    )
    np = state["np"]
    torch = state["torch"]
    donor_faces = state["faces"].tolist()

    texcoords, bound_faces, basecolor, appearance = (
        bake_exavatar_teacher_points_to_canonical_smplx(
            torch=torch,
            np=np,
            donor_positions=state["refined_mesh"],
            donor_faces=donor_faces,
            canonical_uv_template=canonical_uv_template,
            teacher_xyz=state["teacher_xyz"],
            teacher_rgb=state["teacher_rgb"],
            device=state["device"],
        )
    )

    _validate_joint_semantics(
        tuple(state["joint_names"]),
        tuple(SMPLX_JOINT_NAMES),
    )

    student_texcoords, student_faces, student_vertex_count = (
        _first_subdivision_uv_binding(
            texcoords=texcoords,
            bound_faces=bound_faces,
            subdivided_faces=state["first_subdivision_faces"],
            subdivider_source_face_count=state["subdivider_source_face_count"],
        )
    )
    referenced_vertices = {
        vertex
        for face in student_faces
        for vertex, _uv in face
    }
    if (
        not referenced_vertices
        or max(referenced_vertices) >= len(state["teacher_xyz"])
        or max(referenced_vertices) >= len(state["joints4"])
    ):
        raise Quest2StudentCandidateError(
            "Quest2 refined subdivision escapes ExAvatar source/skinning vertices"
        )

    avatar, _thumbnail = _build_vrm(
        np=np,
        name=f"BodyRig performer {request['performer_id']} Quest2 candidate",
        rest_positions=state["teacher_xyz"],
        texcoords=student_texcoords,
        faces=student_faces,
        joints4=state["joints4"],
        weights4=state["weights4"],
        rest_joints=state["zero_joints"],
        parents=state["parents"],
        texture_png=basecolor,
        quality={"nearest_p95": 0.0, "nearest_max": 0.0},
        include_source_vertex_indices=True,
    )
    avatar = _patch_student_vrm(
        avatar,
        teacher_checkpoint_sha256=checkpoint_sha256,
        appearance_metrics=appearance,
    )

    student_dir = output / "student"
    student_dir.mkdir(parents=True)
    avatar_path = student_dir / "avatar.vrm"
    basecolor_path = student_dir / "basecolor.png"
    avatar_path.write_bytes(avatar)
    basecolor_path.write_bytes(basecolor)

    return {
        "avatar": {
            "kind": "student-runtime-package",
            "relative_path": "student/avatar.vrm",
            "size_bytes": avatar_path.stat().st_size,
            "sha256": _sha_file(avatar_path),
        },
        "basecolor": {
            "kind": "teacher-derived-basecolor",
            "relative_path": "student/basecolor.png",
            "size_bytes": basecolor_path.stat().st_size,
            "sha256": _sha_file(basecolor_path),
        },
        "appearance_metrics": appearance,
        "teacher_point_count": int(state["teacher_xyz"].shape[0]),
        "body_vertex_count": int(student_vertex_count),
        "body_face_count": int(len(student_faces)),
        "joint_count": len(state["parents"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a real ExAvatar-derived Quest2 skinned-mesh candidate. "
            "This is deliberately not yet a P3 completion adapter."
        )
    )
    parser.add_argument("--exavatar-workspace-root", type=Path, required=True)
    parser.add_argument("--canonical-uv-template", type=Path, required=True)
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-teacher-root", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-student-representation", required=True)
    parser.add_argument("--bodyrig-student-components", required=True)
    args = parser.parse_args(argv)

    try:
        request = _read_json(
            args.bodyrig_request.expanduser().resolve(),
            label="P3 distillation request",
        )
        revision = _sha(
            args.bodyrig_revision,
            label="P3 adapter revision",
        )
        if _sha_file(Path(__file__).resolve()) != revision:
            raise Quest2StudentCandidateError(
                "Quest2 candidate adapter bytes differ from P3 revision"
            )
        _validate_request(
            request,
            adapter=args.bodyrig_adapter,
            revision=revision,
            representation=args.bodyrig_student_representation,
            student_components=args.bodyrig_student_components,
        )

        output = args.bodyrig_output.expanduser().resolve()
        teacher_root = args.bodyrig_teacher_root.expanduser().resolve()
        workspace = args.exavatar_workspace_root.expanduser().resolve()
        template = args.canonical_uv_template.expanduser().resolve()
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise Quest2StudentCandidateError(
                "Quest2 candidate output directory must exist and be empty"
            )
        if not teacher_root.is_dir() or teacher_root.is_symlink():
            raise Quest2StudentCandidateError(
                "P3 staged teacher root is missing/not regular"
            )
        if not workspace.is_dir() or workspace.is_symlink():
            raise Quest2StudentCandidateError(
                "accepted ExAvatar workspace is missing/not regular"
            )
        if not template.is_file() or template.is_symlink():
            raise Quest2StudentCandidateError(
                "canonical SMPL-X UV template is missing/not regular"
            )

        repo = _verify_workspace(workspace, request)
        sources = _verify_staged_teacher(request, teacher_root)
        subject = "bodyrig-p3-student"

        with tempfile.TemporaryDirectory(
            prefix="bodyrig-p3-exavatar-quest2-"
        ) as temp:
            main_dir = _prepare_exavatar_stage(
                stage=Path(temp),
                repo=repo,
                sources=sources,
                subject=subject,
            )
            candidate = _materialize_candidate(
                request=request,
                main_dir=main_dir,
                canonical_uv_template=template,
                output=output,
                checkpoint_sha256=_sha_file(
                    sources["teacher-checkpoint"]
                ),
            )

        manifest: dict[str, Any] = {
            "format": CANDIDATE_FORMAT,
            "version": VERSION,
            "performer_id": request["performer_id"],
            "selected_epoch_id": request["selected_epoch_id"],
            "teacher_input_sha256": request["teacher_input_sha256"],
            "p3_device_distillation_plan_sha256": request[
                "p3_device_distillation_plan_sha256"
            ],
            "p3_device_distillation_request_sha256": request[
                "p3_device_distillation_request_sha256"
            ],
            "target_model": "quest-2",
            "adapter": request["adapter"],
            "adapter_revision": request["adapter_revision"],
            "student_representation": "skinned-mesh-pbr",
            "required_student_components": list(request["student_components"]),
            "implemented_student_components": [],
            "geometry_source": "accepted-exavatar-refined-first-subdivision-gaussian-surface",
            "appearance_source": "accepted-exavatar-refined-zero-pose-gaussian-rgb",
            "teacher_checkpoint_sha256": _sha_file(
                sources["teacher-checkpoint"]
            ),
            "student_artifacts": [
                candidate["avatar"],
                candidate["basecolor"],
            ],
            "appearance_metrics": candidate["appearance_metrics"],
            "teacher_point_count": candidate["teacher_point_count"],
            "body_vertex_count": candidate["body_vertex_count"],
            "body_face_count": candidate["body_face_count"],
            "joint_count": candidate["joint_count"],
            "student_candidate_complete": True,
            "p3_distillation_complete": False,
            "remaining_blockers": list(BLOCKERS),
            "runtime_acceptance_authority": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        manifest["p3_quest2_student_candidate_sha256"] = _digest(
            manifest,
            omit="p3_quest2_student_candidate_sha256",
        )
        manifest_path = output / "quest2-student-candidate.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "QUEST2_STUDENT_CANDIDATE_MATERIALIZED",
                    "student_candidate_complete": True,
                    "p3_distillation_complete": False,
                    "remaining_blockers": list(BLOCKERS),
                    "runtime_acceptance_authority": False,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Quest2StudentCandidateError as exc:
        print(
            f"BodyRig Quest2 ExAvatar student candidate: FAIL: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
