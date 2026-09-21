from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence


ADAPTER = "bodyrig-exavatar-quest2-pbr-v1"
VERSION = 1
PINNED_EXAVATAR_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
REQUEST_FORMAT = "bodyrig-photoreal-p3-device-distillation-request"
MANIFEST_FORMAT = "bodyrig-photoreal-p3-device-distillation-manifest"
STUDENT_REPRESENTATION = "skinned-mesh-pbr"
STUDENT_COMPONENTS = (
    "specialized-eye-component",
    "teacher-derived-hair-component",
)
FIDELITY_DIMENSIONS = (
    "identity_likeness",
    "face_detail",
    "eyes",
    "hair_silhouette_and_appearance",
    "skin_material_response",
    "hands_and_extremities",
    "motion_identity_preservation",
    "temporal_stability",
)
SMPLX_JOINT_NAMES = (
    "pelvis",
    "left_hip", "right_hip", "spine1",
    "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3",
    "left_foot", "right_foot", "neck",
    "left_collar", "right_collar", "head",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "jaw", "left_eye", "right_eye",
    "left_index1", "left_index2", "left_index3",
    "left_middle1", "left_middle2", "left_middle3",
    "left_pinky1", "left_pinky2", "left_pinky3",
    "left_ring1", "left_ring2", "left_ring3",
    "left_thumb1", "left_thumb2", "left_thumb3",
    "right_index1", "right_index2", "right_index3",
    "right_middle1", "right_middle2", "right_middle3",
    "right_pinky1", "right_pinky2", "right_pinky3",
    "right_ring1", "right_ring2", "right_ring3",
    "right_thumb1", "right_thumb2", "right_thumb3",
)
VRM_HUMANOID = {
    "hips": 0,
    "spine": 3,
    "chest": 6,
    "upperChest": 9,
    "neck": 12,
    "head": 15,
    "leftShoulder": 13,
    "leftUpperArm": 16,
    "leftLowerArm": 18,
    "leftHand": 20,
    "rightShoulder": 14,
    "rightUpperArm": 17,
    "rightLowerArm": 19,
    "rightHand": 21,
    "leftUpperLeg": 1,
    "leftLowerLeg": 4,
    "leftFoot": 7,
    "leftToes": 10,
    "rightUpperLeg": 2,
    "rightLowerLeg": 5,
    "rightFoot": 8,
    "rightToes": 11,
    "leftEye": 23,
    "rightEye": 24,
    "leftIndexProximal": 25,
    "leftIndexIntermediate": 26,
    "leftIndexDistal": 27,
    "leftMiddleProximal": 28,
    "leftMiddleIntermediate": 29,
    "leftMiddleDistal": 30,
    "leftLittleProximal": 31,
    "leftLittleIntermediate": 32,
    "leftLittleDistal": 33,
    "leftRingProximal": 34,
    "leftRingIntermediate": 35,
    "leftRingDistal": 36,
    "leftThumbMetacarpal": 37,
    "leftThumbProximal": 38,
    "leftThumbDistal": 39,
    "rightIndexProximal": 40,
    "rightIndexIntermediate": 41,
    "rightIndexDistal": 42,
    "rightMiddleProximal": 43,
    "rightMiddleIntermediate": 44,
    "rightMiddleDistal": 45,
    "rightLittleProximal": 46,
    "rightLittleIntermediate": 47,
    "rightLittleDistal": 48,
    "rightRingProximal": 49,
    "rightRingIntermediate": 50,
    "rightRingDistal": 51,
    "rightThumbMetacarpal": 52,
    "rightThumbProximal": 53,
    "rightThumbDistal": 54,
)
VRM_EXTENSION = "VRMC_vrm"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ExAvatarQuest2PbrAdapterError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExAvatarQuest2PbrAdapterError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExAvatarQuest2PbrAdapterError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise ExAvatarQuest2PbrAdapterError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise ExAvatarQuest2PbrAdapterError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ExAvatarQuest2PbrAdapterError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExAvatarQuest2PbrAdapterError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise ExAvatarQuest2PbrAdapterError(f"{label} format/version mismatch")


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ExAvatarQuest2PbrAdapterError(f"required file is missing/not regular: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise ExAvatarQuest2PbrAdapterError("artifact cannot be canonically serialized") from exc
    return hashlib.sha256(encoded).hexdigest()


def _relative(value: Any, *, label: str) -> str:
    result = _text(value, label=label).replace("\\", "/")
    first = result.split("/", 1)[0]
    if result.startswith("/") or result.startswith("../") or "/../" in f"/{result}/" or ":" in first:
        raise ExAvatarQuest2PbrAdapterError(f"{label} escapes its root")
    return result


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ExAvatarQuest2PbrAdapterError(f"{label} escapes its root") from exc
    return clean, target


def _request_fields() -> set[str]:
    return {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "target_profile",
        "target_profile_sha256",
        "target_model",
        "adapter",
        "adapter_revision",
        "student_representation",
        "student_components",
        "staged_teacher_sources",
        "required_fidelity_delta_dimensions",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "staged_teacher_only",
        "p3_distillation_execution_authorized",
        "human_runtime_visual_acceptance_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_device_distillation_request_sha256",
    }


def _validate_request(
    request: Mapping[str, Any],
    *,
    teacher_root: Path,
    adapter_revision: str,
) -> list[dict[str, Any]]:
    if set(request) != _request_fields() or request.get("format") != REQUEST_FORMAT:
        raise ExAvatarQuest2PbrAdapterError("P3 request fields/format mismatch")
    _strict_v1(request.get("version"), label="P3 request")
    if request.get("target_model") != "quest-2":
        raise ExAvatarQuest2PbrAdapterError("ExAvatar PBR adapter is pinned to Quest 2")
    if request.get("adapter") != ADAPTER:
        raise ExAvatarQuest2PbrAdapterError("P3 request adapter mismatch")
    if request.get("adapter_revision") != adapter_revision:
        raise ExAvatarQuest2PbrAdapterError("P3 request adapter revision mismatch")
    if request.get("student_representation") != STUDENT_REPRESENTATION:
        raise ExAvatarQuest2PbrAdapterError("P3 request student representation mismatch")
    if request.get("student_components") != list(STUDENT_COMPONENTS):
        raise ExAvatarQuest2PbrAdapterError("P3 request student component universe mismatch")
    if request.get("required_fidelity_delta_dimensions") != list(FIDELITY_DIMENSIONS):
        raise ExAvatarQuest2PbrAdapterError("P3 request fidelity dimension universe mismatch")
    for field, expected in (
        ("teacher_remains_visual_authority", True),
        ("student_may_not_claim_fidelity_above_teacher", True),
        ("staged_teacher_only", True),
        ("p3_distillation_execution_authorized", True),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if request.get(field) is not expected:
            raise ExAvatarQuest2PbrAdapterError(f"P3 request authority mismatch: {field}")
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "p2_animated_human_review_sha256",
        "p3_device_distillation_plan_sha256",
        "target_profile_sha256",
        "adapter_revision",
        "p3_device_distillation_request_sha256",
    ):
        _sha(request.get(field), label=f"P3 request {field}")
    if _digest(request, omit="p3_device_distillation_request_sha256") != request[
        "p3_device_distillation_request_sha256"
    ]:
        raise ExAvatarQuest2PbrAdapterError("P3 request digest mismatch")

    sources = request.get("staged_teacher_sources")
    if not isinstance(sources, list) or len(sources) != 5:
        raise ExAvatarQuest2PbrAdapterError("P3 staged teacher source universe must contain exactly five files")
    expected_kinds = {
        "teacher-checkpoint": "teacher-output",
        "shape-param": "identity-export",
        "face-offset": "identity-export",
        "joint-offset": "identity-export",
        "locator-offset": "identity-export",
    }
    observed_kinds: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sources:
        if not isinstance(raw, Mapping) or set(raw) != {
            "kind", "root_kind", "relative_path", "size_bytes", "sha256"
        }:
            raise ExAvatarQuest2PbrAdapterError("P3 staged teacher source fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="P3 teacher source kind", maximum=64)
        root_kind = _text(raw.get("root_kind"), label="P3 teacher source root kind", maximum=64)
        relative, path = _safe_child(
            teacher_root,
            raw.get("relative_path"),
            label="P3 staged teacher source path",
        )
        if relative in seen:
            raise ExAvatarQuest2PbrAdapterError("P3 request repeats staged teacher source")
        seen.add(relative)
        observed_kinds[kind] = root_kind
        size = raw.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
        ):
            raise ExAvatarQuest2PbrAdapterError(f"P3 staged teacher source size/path drifted: {relative}")
        expected_sha = _sha(raw.get("sha256"), label="P3 staged teacher source SHA-256")
        if _file_sha(path) != expected_sha:
            raise ExAvatarQuest2PbrAdapterError(f"P3 staged teacher source bytes drifted: {relative}")
        normalized.append(
            {
                "kind": kind,
                "root_kind": root_kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": expected_sha,
            }
        )
    if observed_kinds != expected_kinds:
        raise ExAvatarQuest2PbrAdapterError("P3 staged teacher kind/root universe mismatch")
    normalized.sort(key=lambda item: (item["root_kind"], item["kind"], item["relative_path"]))
    return normalized


def _source_path(sources: Sequence[Mapping[str, Any]], teacher_root: Path, kind: str) -> Path:
    matches = [item for item in sources if item.get("kind") == kind]
    if len(matches) != 1:
        raise ExAvatarQuest2PbrAdapterError(f"P3 staged teacher source is not unique: {kind}")
    _, path = _safe_child(teacher_root, matches[0]["relative_path"], label=f"P3 {kind} path")
    return path


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
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
        raise ExAvatarQuest2PbrAdapterError(
            "could not verify pinned ExAvatar checkout" + (f": {detail}" if detail else "")
        )
    return (completed.stdout or "").strip()


def _validate_exavatar_workspace(root: Path, runtime_preflight: Path) -> tuple[Path, str]:
    if not root.is_dir():
        raise ExAvatarQuest2PbrAdapterError(f"ExAvatar workspace not found: {root}")
    receipt = _read_json(root / "workspace-receipt.json", label="ExAvatar workspace receipt")
    if receipt.get("upstream_commit") != PINNED_EXAVATAR_COMMIT:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar workspace upstream commit mismatch")
    repositories = receipt.get("repository_commits")
    if not isinstance(repositories, Mapping) or repositories.get("exavatar") != PINNED_EXAVATAR_COMMIT:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar workspace repository provenance mismatch")
    gender = _text(receipt.get("smplx_gender"), label="ExAvatar SMPL-X gender", maximum=16).lower()
    if gender not in {"neutral", "male", "female"}:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar workspace SMPL-X gender is unsupported")
    repo = root / "repos" / "ExAvatar_RELEASE"
    if _git_head(repo) != PINNED_EXAVATAR_COMMIT:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar checkout HEAD differs from pinned upstream commit")

    preflight = _read_json(runtime_preflight, label="ExAvatar runtime preflight")
    if preflight.get("runtime_environment_ready") is not True or preflight.get("blockers") != []:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar runtime preflight is not ready")
    return repo, gender


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _thumbnail_png(width: int = 128, height: int = 128) -> bytes:
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            nx = (x - width / 2) / width
            ny = y / height
            head = nx * nx + ((ny - 0.22) / 0.12) ** 2 < 0.025
            torso = 0.34 < ny < 0.72 and abs(nx) < 0.15 + 0.04 * (0.72 - ny)
            legs = ny >= 0.69 and (abs(nx - 0.065) < 0.055 or abs(nx + 0.065) < 0.055)
            arms = 0.39 < ny < 0.68 and abs(nx) < 0.29 and not torso
            alpha = 255 if head or torso or legs or arms else 0
            row.extend((205, 205, 210, alpha))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(rows)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _pad4(data: bytes, pad: bytes) -> bytes:
    return data + pad * ((-len(data)) % 4)


def _glb(document: dict[str, Any], binary: bytes) -> bytes:
    json_chunk = _pad4(
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8"),
        b" ",
    )
    bin_chunk = _pad4(binary, b"\x00")
    chunks = struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    if bin_chunk:
        chunks += struct.pack("<I4s", len(bin_chunk), b"BIN\x00") + bin_chunk
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _top4_skinning(np: Any, weights: Any) -> tuple[Any, Any]:
    matrix = np.asarray(weights, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != len(SMPLX_JOINT_NAMES):
        raise ExAvatarQuest2PbrAdapterError("ExAvatar skinning weight matrix is not 55-joint SMPL-X")
    order = np.argsort(matrix, axis=1)[:, -4:][:, ::-1]
    selected = np.take_along_axis(matrix, order, axis=1)
    total = selected.sum(axis=1, keepdims=True)
    if np.any(total <= 1e-8):
        raise ExAvatarQuest2PbrAdapterError("ExAvatar skinning contains an empty top-4 influence set")
    selected = selected / total
    return order.astype(np.uint16), selected.astype(np.float32)


def _component_masks(np: Any, dominant_joints: Any, face_mask: Any) -> tuple[Any, Any]:
    dominant = np.asarray(dominant_joints, dtype=np.int64).reshape(-1)
    face = np.asarray(face_mask, dtype=bool).reshape(-1)
    if dominant.shape != face.shape:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar component masks are shape-incompatible")
    eye = np.isin(dominant, np.asarray([23, 24], dtype=np.int64))
    hair = (dominant == 15) & (~face) & (~eye)
    if not np.any(hair):
        hair = np.isin(dominant, np.asarray([12, 15], dtype=np.int64)) & (~face) & (~eye)
    if not np.any(eye):
        raise ExAvatarQuest2PbrAdapterError("ExAvatar topology produced no eye-weighted vertices")
    if not np.any(hair):
        raise ExAvatarQuest2PbrAdapterError("ExAvatar topology produced no teacher-derived hair/scalp vertices")
    return eye, hair


def _partition_faces(np: Any, faces: Any, eye_mask: Any, hair_mask: Any) -> tuple[Any, Any, Any]:
    tri = np.asarray(faces, dtype=np.int64)
    if tri.ndim != 2 or tri.shape[1] != 3 or tri.shape[0] < 1:
        raise ExAvatarQuest2PbrAdapterError("ExAvatar upsampled face topology is invalid")
    eye_votes = np.asarray(eye_mask, dtype=np.int8)[tri].sum(axis=1)
    hair_votes = np.asarray(hair_mask, dtype=np.int8)[tri].sum(axis=1)
    is_eye = eye_votes >= 2
    is_hair = (~is_eye) & (hair_votes >= 2)
    is_base = ~(is_eye | is_hair)
    base = tri[is_base]
    eyes = tri[is_eye]
    hair = tri[is_hair]
    if len(base) < 1 or len(eyes) < 1 or len(hair) < 1:
        raise ExAvatarQuest2PbrAdapterError(
            "ExAvatar topology could not form non-empty base/eye/hair Quest primitives"
        )
    return base, eyes, hair


def _build_vertex_color_vrm(
    np: Any,
    *,
    name: str,
    positions: Any,
    colors: Any,
    faces: Any,
    joints4: Any,
    weights4: Any,
    rest_joints: Any,
    parents: Sequence[int],
    eye_mask: Any,
    hair_mask: Any,
) -> tuple[bytes, dict[str, int]]:
    positions_arr = np.asarray(positions, dtype=np.float32)
    colors_rgb = np.clip(np.asarray(colors, dtype=np.float32), 0.0, 1.0)
    joints_arr = np.asarray(joints4, dtype=np.uint16)
    weights_arr = np.asarray(weights4, dtype=np.float32)
    rest = np.asarray(rest_joints, dtype=np.float32)
    if positions_arr.ndim != 2 or positions_arr.shape[1] != 3 or len(positions_arr) < 3:
        raise ExAvatarQuest2PbrAdapterError("student positions are invalid")
    if colors_rgb.shape != positions_arr.shape:
        raise ExAvatarQuest2PbrAdapterError("student vertex colors do not match positions")
    if joints_arr.shape != (len(positions_arr), 4) or weights_arr.shape != (len(positions_arr), 4):
        raise ExAvatarQuest2PbrAdapterError("student skinning arrays do not match positions")
    if rest.shape != (len(SMPLX_JOINT_NAMES), 3) or len(parents) != len(SMPLX_JOINT_NAMES):
        raise ExAvatarQuest2PbrAdapterError("student SMPL-X skeleton is not 55-joint canonical")

    base_faces, eye_faces, hair_faces = _partition_faces(np, faces, eye_mask, hair_mask)
    all_faces = np.asarray(faces, dtype=np.int64)
    if int(all_faces.max()) >= len(positions_arr) or int(all_faces.min()) < 0:
        raise ExAvatarQuest2PbrAdapterError("student face topology references invalid vertices")

    normals = np.zeros_like(positions_arr)
    for a, b, c in all_faces:
        edge1 = positions_arr[b] - positions_arr[a]
        edge2 = positions_arr[c] - positions_arr[a]
        normal = np.cross(edge1, edge2)
        normals[a] += normal
        normals[b] += normal
        normals[c] += normal
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
    colors_arr = np.concatenate(
        [colors_rgb, np.ones((len(colors_rgb), 1), dtype=np.float32)],
        axis=1,
    )

    joint_nodes: list[dict[str, Any]] = []
    parents_list = [int(value) for value in parents]
    for index, joint_name in enumerate(SMPLX_JOINT_NAMES):
        parent = parents_list[index]
        if index == 0:
            translation = rest[index]
        else:
            if parent < 0 or parent >= index:
                raise ExAvatarQuest2PbrAdapterError("student SMPL-X parent topology is invalid")
            translation = rest[index] - rest[parent]
        joint_nodes.append(
            {
                "name": f"smplx_{joint_name}",
                "translation": [float(value) for value in translation],
            }
        )
    for index in range(1, len(joint_nodes)):
        joint_nodes[parents_list[index]].setdefault("children", []).append(index)

    mesh_node = len(joint_nodes)
    nodes = [*joint_nodes, {"name": name, "mesh": 0, "skin": 0}]
    human_bones = {bone: {"node": index} for bone, index in VRM_HUMANOID.items()}

    inverse_bind: list[float] = []
    for joint in rest:
        x, y, z = (float(value) for value in joint)
        inverse_bind.extend(
            (
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                -x, -y, -z, 1.0,
            )
        )
    ibm_arr = np.asarray(inverse_bind, dtype=np.float32).reshape(-1, 16)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        item: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            item["target"] = target
        buffer_views.append(item)
        return len(buffer_views) - 1

    def add_accessor(
        raw: bytes,
        *,
        component: int,
        count: int,
        kind: str,
        target: int | None = None,
        minimum: list[float] | None = None,
        maximum: list[float] | None = None,
    ) -> int:
        view = add_view(raw, target=target)
        item: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": count,
            "type": kind,
        }
        if minimum is not None:
            item["min"] = minimum
        if maximum is not None:
            item["max"] = maximum
        accessors.append(item)
        return len(accessors) - 1

    pos_accessor = add_accessor(
        positions_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(positions_arr),
        kind="VEC3",
        target=34962,
        minimum=[float(value) for value in positions_arr.min(axis=0)],
        maximum=[float(value) for value in positions_arr.max(axis=0)],
    )
    normal_accessor = add_accessor(
        normals.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(normals),
        kind="VEC3",
        target=34962,
    )
    color_accessor = add_accessor(
        colors_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(colors_arr),
        kind="VEC4",
        target=34962,
    )
    joints_accessor = add_accessor(
        joints_arr.astype("<u2", copy=False).tobytes(),
        component=5123,
        count=len(joints_arr),
        kind="VEC4",
        target=34962,
    )
    weights_accessor = add_accessor(
        weights_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(weights_arr),
        kind="VEC4",
        target=34962,
    )

    def index_accessor(triangles: Any) -> int:
        arr = np.asarray(triangles, dtype=np.uint32).reshape(-1)
        return add_accessor(
            arr.astype("<u4", copy=False).tobytes(),
            component=5125,
            count=int(arr.size),
            kind="SCALAR",
            target=34963,
        )

    base_indices = index_accessor(base_faces)
    eye_indices = index_accessor(eye_faces)
    hair_indices = index_accessor(hair_faces)
    ibm_accessor = add_accessor(
        ibm_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(rest),
        kind="MAT4",
    )
    thumbnail = _thumbnail_png()
    thumbnail_view = add_view(thumbnail)

    common_attributes = {
        "POSITION": pos_accessor,
        "NORMAL": normal_accessor,
        "COLOR_0": color_accessor,
        "JOINTS_0": joints_accessor,
        "WEIGHTS_0": weights_accessor,
    }
    document: dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "BodyRig ExAvatar Quest2 PBR Student v1",
        },
        "extensionsUsed": [VRM_EXTENSION],
        "extensionsRequired": [VRM_EXTENSION],
        "extensions": {
            VRM_EXTENSION: {
                "specVersion": "1.0",
                "meta": {
                    "name": name,
                    "version": "1",
                    "authors": ["BodyRig"],
                    "licenseUrl": "https://vrm.dev/licenses/1.0/",
                    "avatarPermission": "onlyAuthor",
                    "commercialUsage": "personalNonProfit",
                    "creditNotation": "required",
                    "allowRedistribution": False,
                    "modification": "prohibited",
                    "thumbnailImage": 0,
                },
                "humanoid": {"humanBones": human_bones},
            }
        },
        "scene": 0,
        "scenes": [{"nodes": [0, mesh_node]}],
        "nodes": nodes,
        "meshes": [
            {
                "name": "BodyRigExAvatarTeacherDerivedStudent",
                "primitives": [
                    {
                        "attributes": dict(common_attributes),
                        "indices": base_indices,
                        "material": 0,
                        "mode": 4,
                        "extras": {"bodyrigComponent": "base-skinned-mesh"},
                    },
                    {
                        "attributes": dict(common_attributes),
                        "indices": eye_indices,
                        "material": 1,
                        "mode": 4,
                        "extras": {"bodyrigComponent": "specialized-eye-component"},
                    },
                    {
                        "attributes": dict(common_attributes),
                        "indices": hair_indices,
                        "material": 2,
                        "mode": 4,
                        "extras": {"bodyrigComponent": "teacher-derived-hair-component"},
                    },
                ],
            }
        ],
        "skins": [
            {
                "name": "SMPLX",
                "inverseBindMatrices": ibm_accessor,
                "skeleton": 0,
                "joints": list(range(len(SMPLX_JOINT_NAMES))),
            }
        ],
        "materials": [
            {
                "name": "BodyRigTeacherDerivedBodyPBR",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.82,
                },
            },
            {
                "name": "BodyRigTeacherDerivedEyesPBR",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.22,
                },
            },
            {
                "name": "BodyRigTeacherDerivedHairPBR",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.72,
                },
            },
        ],
        "images": [
            {
                "name": "BodyRigThumbnail",
                "bufferView": thumbnail_view,
                "mimeType": "image/png",
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "bodyrig": {
                "placeholder": False,
                "teacherDerived": True,
                "teacher": "ExAvatar",
                "teacherCommit": PINNED_EXAVATAR_COMMIT,
                "studentRepresentation": STUDENT_REPRESENTATION,
                "studentComponents": list(STUDENT_COMPONENTS),
                "appearanceEncoding": "per-vertex-color0-from-exavatar-refined-rgb",
                "componentFaceCounts": {
                    "base": int(len(base_faces)),
                    "eyes": int(len(eye_faces)),
                    "hair": int(len(hair_faces)),
                },
            }
        },
    }
    return _glb(document, bytes(binary)), {
        "base_face_count": int(len(base_faces)),
        "eye_face_count": int(len(eye_faces)),
        "hair_face_count": int(len(hair_faces)),
    }


def _rmse(np: Any, left: Any, right: Any) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        raise ExAvatarQuest2PbrAdapterError("fidelity arrays are empty/shape-incompatible")
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _masked_rmse(np: Any, left: Any, right: Any, mask: Any) -> float:
    m = np.asarray(mask, dtype=bool).reshape(-1)
    a = np.asarray(left)
    b = np.asarray(right)
    if a.shape != b.shape or a.shape[0] != len(m) or not np.any(m):
        raise ExAvatarQuest2PbrAdapterError("fidelity mask is empty/shape-incompatible")
    return _rmse(np, a[m], b[m])


def _measurement(
    dimension: str,
    metric: str,
    value: float,
    unit: str,
    *,
    teacher_reference: str,
    student_reference: str,
) -> dict[str, Any]:
    if dimension not in FIDELITY_DIMENSIONS or not math.isfinite(float(value)) or float(value) < 0:
        raise ExAvatarQuest2PbrAdapterError(f"invalid fidelity measurement: {dimension}")
    return {
        "dimension": dimension,
        "metric": metric,
        "value": round(float(value), 9),
        "unit": unit,
        "teacher_reference": teacher_reference,
        "student_reference": student_reference,
    }


def _pose_params(torch: Any, smpl_x: Any, pose_index: int) -> dict[str, Any]:
    if pose_index not in range(5):
        raise ExAvatarQuest2PbrAdapterError("canonical pose index is invalid")
    body = torch.zeros(((len(smpl_x.joint_part["body"]) - 1) * 3), dtype=torch.float32, device="cuda")
    jaw = torch.zeros((3), dtype=torch.float32, device="cuda")
    leye = torch.zeros((3), dtype=torch.float32, device="cuda")
    reye = torch.zeros((3), dtype=torch.float32, device="cuda")
    lhand = torch.zeros((len(smpl_x.joint_part["lhand"]) * 3), dtype=torch.float32, device="cuda")
    rhand = torch.zeros((len(smpl_x.joint_part["rhand"]) * 3), dtype=torch.float32, device="cuda")
    if pose_index == 1:
        body[15 * 3 + 2] = -0.55
        body[17 * 3 + 1] = -0.45
    elif pose_index == 2:
        body[16 * 3 + 2] = 0.55
        body[18 * 3 + 1] = 0.45
    elif pose_index == 3:
        body[2 * 3 + 1] = 0.25
        body[14 * 3 + 1] = 0.35
        jaw[0] = 0.18
    elif pose_index == 4:
        body[2 * 3 + 1] = -0.25
        body[14 * 3 + 1] = -0.35
        leye[1] = 0.12
        reye[1] = -0.12
        lhand[0] = 0.25
        rhand[0] = -0.25
    return {
        "root_pose": torch.zeros((3), dtype=torch.float32, device="cuda"),
        "body_pose": body,
        "jaw_pose": jaw,
        "leye_pose": leye,
        "reye_pose": reye,
        "lhand_pose": lhand,
        "rhand_pose": rhand,
        "expr": torch.zeros((smpl_x.expr_param_dim), dtype=torch.float32, device="cuda"),
        "trans": torch.zeros((3), dtype=torch.float32, device="cuda"),
    }


def _load_teacher_and_export(
    *,
    exavatar_repo: Path,
    gender: str,
    checkpoint_path: Path,
    shape_path: Path,
    face_offset_path: Path,
    joint_offset_path: Path,
    locator_offset_path: Path,
) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
        from pytorch3d.ops import knn_points
    except ImportError as exc:
        raise ExAvatarQuest2PbrAdapterError(
            "ExAvatar Quest2 PBR export requires numpy, torch and pytorch3d"
        ) from exc
    if not torch.cuda.is_available():
        raise ExAvatarQuest2PbrAdapterError("ExAvatar Quest2 PBR export requires CUDA")

    avatar_main = exavatar_repo / "avatar" / "main"
    common = exavatar_repo / "avatar" / "common"
    if not avatar_main.is_dir() or not common.is_dir():
        raise ExAvatarQuest2PbrAdapterError("pinned ExAvatar avatar source tree is incomplete")
    old_cwd = Path.cwd()
    inserted = [str(avatar_main), str(common)]
    for item in reversed(inserted):
        if item not in sys.path:
            sys.path.insert(0, item)
    try:
        os.chdir(avatar_main)
        from config import cfg  # type: ignore
        cfg.smplx_gender = gender
        from utils.smpl_x import smpl_x  # type: ignore
        from nets.module import HumanGaussian  # type: ignore

        def load_vector(path: Path, label: str) -> Any:
            value = _read_json(path, label=label)
            raise ExAvatarQuest2PbrAdapterError(
                f"{label} must be a JSON array, not an object"
            )

        def load_array(path: Path, label: str) -> Any:
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ExAvatarQuest2PbrAdapterError(f"{label} is unreadable") from exc
            if not isinstance(value, list) or not value:
                raise ExAvatarQuest2PbrAdapterError(f"{label} must be a non-empty JSON array")
            return torch.tensor(value, dtype=torch.float32)

        shape = load_array(shape_path, "ExAvatar shape_param")
        face_offset = load_array(face_offset_path, "ExAvatar face_offset")
        joint_offset = load_array(joint_offset_path, "ExAvatar joint_offset")
        locator_offset = load_array(locator_offset_path, "ExAvatar locator_offset")
        smpl_x.set_id_info(shape, face_offset, joint_offset, locator_offset)

        human = HumanGaussian()
        human.init()
        human = human.cuda()

        try:
            checkpoint = torch.load(checkpoint_path, map_location="cpu")
        except Exception as exc:
            raise ExAvatarQuest2PbrAdapterError("accepted ExAvatar checkpoint could not be loaded") from exc
        if not isinstance(checkpoint, Mapping) or not isinstance(checkpoint.get("network"), Mapping):
            raise ExAvatarQuest2PbrAdapterError("accepted ExAvatar checkpoint has invalid network state")
        prefix = "human_gaussian."
        state = {
            str(key)[len(prefix):]: value
            for key, value in checkpoint["network"].items()
            if str(key).startswith(prefix)
        }
        if not state:
            raise ExAvatarQuest2PbrAdapterError("accepted ExAvatar checkpoint contains no HumanGaussian state")
        try:
            human.load_state_dict(state, strict=True)
        except Exception as exc:
            raise ExAvatarQuest2PbrAdapterError(
                "accepted ExAvatar HumanGaussian state does not match pinned code"
            ) from exc
        human.eval()

        cam = {
            "R": torch.eye(3, dtype=torch.float32, device="cuda"),
            "t": torch.zeros((3), dtype=torch.float32, device="cuda"),
            "focal": torch.tensor([1500.0, 1500.0], dtype=torch.float32, device="cuda"),
            "princpt": torch.tensor([512.0, 512.0], dtype=torch.float32, device="cuda"),
        }
        zero_param = _pose_params(torch, smpl_x, 0)
        with torch.no_grad():
            base_zero, refined_zero, offsets_zero, _ = human(
                zero_param,
                cam,
                is_world_coord=True,
            )
            _, _, rest_joints_tensor = human.get_zero_pose_human(return_mesh=True)

            mesh_neutral, mesh_neutral_low, _, _ = human.get_neutral_pose_human(
                jaw_zero_pose=True,
                use_id_info=True,
            )
            tri_feat = human.extract_tri_feature()
            geo_feat = human.geo_net(tri_feat)
            mean_offset = human.mean_offset_net(geo_feat)
            neutral_offset_points = mesh_neutral + mean_offset
            nn_vertex_idxs = knn_points(
                neutral_offset_points[None, :, :],
                mesh_neutral_low[None, :, :],
                K=1,
                return_nn=True,
            ).idx[0, :, 0]
            nn_vertex_idxs = human.lr_idx_to_hr_idx(nn_vertex_idxs)
            face_hand_mask = (human.is_rhand + human.is_lhand + human.is_face) > 0
            nn_vertex_idxs[face_hand_mask] = torch.arange(
                smpl_x.vertex_num_upsampled,
                device="cuda",
            )[face_hand_mask]
            effective_weights = human.skinning_weight[nn_vertex_idxs, :]

            positions = refined_zero["mean_3d"].detach().cpu().numpy().astype(np.float32)
            colors = refined_zero["rgb"].detach().cpu().numpy().astype(np.float32)
            base_positions = base_zero["mean_3d"].detach().cpu().numpy().astype(np.float32)
            rest_joints = rest_joints_tensor.detach().cpu().numpy().astype(np.float32)
            weights = effective_weights.detach().cpu().numpy().astype(np.float32)
            face_mask = human.is_face.detach().cpu().numpy().astype(bool)
            lhand_mask = human.is_lhand.detach().cpu().numpy().astype(bool)
            rhand_mask = human.is_rhand.detach().cpu().numpy().astype(bool)
            faces = np.asarray(smpl_x.face_upsampled, dtype=np.int64)
            parents = [int(value) for value in human.smplx_layer.parents[: len(SMPLX_JOINT_NAMES)].detach().cpu().tolist()]

            joints4, weights4 = _top4_skinning(np, weights)
            dominant = np.argmax(weights, axis=1)
            eye_mask, hair_mask = _component_masks(np, dominant, face_mask)
            hand_mask = lhand_mask | rhand_mask
            skin_mask = ~(eye_mask | hair_mask)
            body_height = float(np.max(positions[:, 1]) - np.min(positions[:, 1]))
            if not math.isfinite(body_height) or body_height <= 1e-6:
                raise ExAvatarQuest2PbrAdapterError("ExAvatar zero-pose body height is invalid")

            student_positions = positions.astype(np.float32, copy=True)
            student_colors = colors.astype(np.float32, copy=True)
            measurements = [
                _measurement(
                    "identity_likeness",
                    "teacher-zero-pose-vertex-position-rmse/body-height",
                    _rmse(np, positions, student_positions) / body_height,
                    "normalized-rmse",
                    teacher_reference="exavatar-refined-zero-pose-vertices",
                    student_reference="quest2-vrm-position-payload",
                ),
                _measurement(
                    "face_detail",
                    "teacher-zero-pose-face-rgb-rmse",
                    _masked_rmse(np, colors, student_colors, face_mask),
                    "rgb-0-1-rmse",
                    teacher_reference="exavatar-refined-zero-pose-face-rgb",
                    student_reference="quest2-vrm-color0-face-payload",
                ),
                _measurement(
                    "eyes",
                    "teacher-zero-pose-eye-rgb-rmse",
                    _masked_rmse(np, colors, student_colors, eye_mask),
                    "rgb-0-1-rmse",
                    teacher_reference="exavatar-refined-zero-pose-eye-rgb",
                    student_reference="quest2-vrm-specialized-eye-color0",
                ),
                _measurement(
                    "hair_silhouette_and_appearance",
                    "teacher-zero-pose-hair-geometry-rmse/body-height",
                    _masked_rmse(np, positions, student_positions, hair_mask) / body_height,
                    "normalized-rmse",
                    teacher_reference="exavatar-refined-head-nonface-vertices",
                    student_reference="quest2-vrm-teacher-derived-hair-primitive",
                ),
                _measurement(
                    "skin_material_response",
                    "teacher-zero-pose-skin-rgb-rmse",
                    _masked_rmse(np, colors, student_colors, skin_mask),
                    "rgb-0-1-rmse",
                    teacher_reference="exavatar-refined-zero-pose-skin-rgb",
                    student_reference="quest2-vrm-pbr-color0-skin-payload",
                ),
                _measurement(
                    "hands_and_extremities",
                    "teacher-zero-pose-hand-geometry-rmse/body-height",
                    _masked_rmse(np, positions, student_positions, hand_mask) / body_height,
                    "normalized-rmse",
                    teacher_reference="exavatar-refined-zero-pose-hand-vertices",
                    student_reference="quest2-vrm-skinned-hand-vertices",
                ),
            ]

            residuals: list[Any] = []
            for pose_index in range(5):
                params = _pose_params(torch, smpl_x, pose_index)
                base_asset, refined_asset, _, _ = human(
                    params,
                    cam,
                    is_world_coord=True,
                )
                base_np = base_asset["mean_3d"].detach().cpu().numpy().astype(np.float32)
                refined_np = refined_asset["mean_3d"].detach().cpu().numpy().astype(np.float32)
                residuals.append(refined_np - base_np)
            zero_residual = residuals[0]
            motion_residual = np.stack(
                [item - zero_residual for item in residuals[1:]],
                axis=0,
            )
            motion_delta = float(np.sqrt(np.mean(motion_residual.astype(np.float64) ** 2))) / body_height
            residual_stack = np.stack(residuals, axis=0).astype(np.float64)
            temporal_delta = float(np.sqrt(np.mean(np.diff(residual_stack, axis=0) ** 2))) / body_height
            measurements.extend(
                [
                    _measurement(
                        "motion_identity_preservation",
                        "exavatar-pose-dependent-refinement-residual-rmse/body-height",
                        motion_delta,
                        "normalized-rmse",
                        teacher_reference="exavatar-refined-canonical-pose-sweep-v1",
                        student_reference="quest2-static-rest-plus-smplx-skinning-v1",
                    ),
                    _measurement(
                        "temporal_stability",
                        "exavatar-refinement-frame-delta-rmse/body-height",
                        temporal_delta,
                        "normalized-rmse",
                        teacher_reference="exavatar-refined-canonical-pose-sweep-v1",
                        student_reference="quest2-static-rest-plus-smplx-skinning-v1",
                    ),
                ]
            )

        vrm_bytes, component_counts = _build_vertex_color_vrm(
            np,
            name="BodyRig ExAvatar Quest2 Student",
            positions=student_positions,
            colors=student_colors,
            faces=faces,
            joints4=joints4,
            weights4=weights4,
            rest_joints=rest_joints,
            parents=parents,
            eye_mask=eye_mask,
            hair_mask=hair_mask,
        )
        return {
            "vrm_bytes": vrm_bytes,
            "measurements": measurements,
            "vertex_count": int(len(student_positions)),
            "triangle_count": int(len(faces)),
            "body_height": body_height,
            "component_counts": component_counts,
            "eye_vertex_count": int(np.count_nonzero(eye_mask)),
            "hair_vertex_count": int(np.count_nonzero(hair_mask)),
            "face_vertex_count": int(np.count_nonzero(face_mask)),
            "hand_vertex_count": int(np.count_nonzero(hand_mask)),
            "zero_pose_refinement_rms": _rmse(np, positions, base_positions),
        }
    finally:
        os.chdir(old_cwd)


def _artifact(path: Path, root: Path, *, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha(path),
    }


def _run_linux(args: argparse.Namespace) -> int:
    request_path = Path(args.bodyrig_request).expanduser().resolve()
    teacher_root = Path(args.bodyrig_teacher_root).expanduser().resolve()
    output_root = Path(args.bodyrig_output).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    runtime_preflight = Path(args.runtime_preflight).expanduser().resolve()
    if not request_path.is_file() or not teacher_root.is_dir() or not output_root.is_dir():
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 adapter boundary paths are invalid")
    if any(output_root.iterdir()):
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 adapter output must start empty")
    if args.bodyrig_adapter != ADAPTER:
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 adapter identity mismatch")
    revision = _sha(args.bodyrig_revision, label="BodyRig P3 adapter revision")
    if _file_sha(Path(__file__).resolve()) != revision:
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 adapter revision does not match exact entrypoint bytes")
    if args.bodyrig_student_representation != STUDENT_REPRESENTATION:
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 student representation mismatch")
    components = [item for item in args.bodyrig_student_components.split(",") if item]
    if components != list(STUDENT_COMPONENTS):
        raise ExAvatarQuest2PbrAdapterError("BodyRig P3 student component universe mismatch")

    request = _read_json(request_path, label="P3 distillation request")
    sources = _validate_request(request, teacher_root=teacher_root, adapter_revision=revision)
    exavatar_repo, gender = _validate_exavatar_workspace(workspace_root, runtime_preflight)

    exported = _load_teacher_and_export(
        exavatar_repo=exavatar_repo,
        gender=gender,
        checkpoint_path=_source_path(sources, teacher_root, "teacher-checkpoint"),
        shape_path=_source_path(sources, teacher_root, "shape-param"),
        face_offset_path=_source_path(sources, teacher_root, "face-offset"),
        joint_offset_path=_source_path(sources, teacher_root, "joint-offset"),
        locator_offset_path=_source_path(sources, teacher_root, "locator-offset"),
    )
    measurements = exported["measurements"]
    if [item["dimension"] for item in measurements] != list(FIDELITY_DIMENSIONS):
        raise ExAvatarQuest2PbrAdapterError("P3 adapter did not produce canonical fidelity dimensions")

    student_root = output_root / "student"
    student_root.mkdir()
    vrm_path = student_root / "avatar.vrm"
    vrm_path.write_bytes(exported["vrm_bytes"])
    provenance_path = student_root / "exavatar-quest2-pbr-provenance.json"
    provenance = {
        "format": "bodyrig-exavatar-quest2-pbr-student-provenance",
        "version": 1,
        "adapter": ADAPTER,
        "adapter_revision": revision,
        "exavatar_upstream_commit": PINNED_EXAVATAR_COMMIT,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "target_model": "quest-2",
        "student_representation": STUDENT_REPRESENTATION,
        "student_components": list(STUDENT_COMPONENTS),
        "geometry_source": "accepted-exavatar-human-gaussian-refined-zero-pose",
        "appearance_source": "accepted-exavatar-human-gaussian-refined-rgb-color0",
        "animation_source": "smplx-55-joint-skinning-top4",
        "specialized_eye_policy": "dominant-l_eye-r_eye-skinning-primitive",
        "teacher_derived_hair_policy": "head-dominant-nonface-teacher-vertex-primitive",
        "vertex_count": exported["vertex_count"],
        "triangle_count": exported["triangle_count"],
        "body_height": round(exported["body_height"], 9),
        "component_counts": exported["component_counts"],
        "eye_vertex_count": exported["eye_vertex_count"],
        "hair_vertex_count": exported["hair_vertex_count"],
        "face_vertex_count": exported["face_vertex_count"],
        "hand_vertex_count": exported["hand_vertex_count"],
        "zero_pose_refinement_rms": round(exported["zero_pose_refinement_rms"], 9),
        "fidelity_delta_measurements": measurements,
        "fidelity_measurement_policy": {
            "static_dimensions": "exact-retained-teacher-zero-pose-payload-rmse",
            "motion_identity_preservation": "canonical-pose-sweep-v1 omitted dynamic refinement residual",
            "temporal_stability": "canonical-pose-sweep-v1 refinement frame-delta residual",
            "human_runtime_visual_acceptance_required": True,
        },
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    provenance["student_provenance_sha256"] = _digest(
        provenance,
        omit="student_provenance_sha256",
    )
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    artifacts = [
        _artifact(vrm_path, output_root, kind="quest2-vrm-student-runtime"),
        _artifact(provenance_path, output_root, kind="exavatar-quest2-pbr-provenance"),
    ]
    artifacts.sort(key=lambda item: item["relative_path"])
    consumed = [
        {
            "kind": item["kind"],
            "root_kind": item["root_kind"],
            "relative_path": item["relative_path"],
            "sha256": item["sha256"],
        }
        for item in sources
    ]
    consumed.sort(key=lambda item: (item["root_kind"], item["kind"], item["relative_path"]))

    manifest = {
        "format": MANIFEST_FORMAT,
        "version": VERSION,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "p2_animation_plan_sha256": request["p2_animation_plan_sha256"],
        "p2_exavatar_animation_execution_input_sha256": request[
            "p2_exavatar_animation_execution_input_sha256"
        ],
        "p2_animated_human_review_sha256": request["p2_animated_human_review_sha256"],
        "p3_device_distillation_plan_sha256": request["p3_device_distillation_plan_sha256"],
        "p3_device_distillation_request_sha256": request["p3_device_distillation_request_sha256"],
        "target_profile_sha256": request["target_profile_sha256"],
        "target_model": "quest-2",
        "adapter": ADAPTER,
        "adapter_revision": revision,
        "student_representation": STUDENT_REPRESENTATION,
        "student_components": list(STUDENT_COMPONENTS),
        "distillation_complete": True,
        "consumed_teacher_sources": consumed,
        "fidelity_delta_measurements": measurements,
        "student_artifacts": artifacts,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    manifest_path = output_root / "distillation-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "EXAVATAR_QUEST2_PBR_STUDENT_MATERIALIZED",
                "vertex_count": exported["vertex_count"],
                "triangle_count": exported["triangle_count"],
                "student_artifact_count": len(artifacts),
                "fidelity_delta_dimension_count": len(measurements),
                "human_runtime_visual_acceptance_required": True,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _wsl_path(wsl_exe: str, distribution: str, path: Path) -> str:
    completed = subprocess.run(
        [wsl_exe, "-d", distribution, "--", "/usr/bin/wslpath", "-a", "-u", str(path)],
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
        raise ExAvatarQuest2PbrAdapterError(
            "could not translate BodyRig path into WSL" + (f": {detail}" if detail else "")
        )
    value = (completed.stdout or "").strip()
    if not value.startswith("/") or "\n" in value or "\r" in value:
        raise ExAvatarQuest2PbrAdapterError("WSL path translation returned an invalid path")
    return value


def _run_windows_bridge(args: argparse.Namespace) -> int:
    distribution = _text(args.distribution, label="WSL distribution", maximum=160)
    linux_python = _text(args.linux_python, label="ExAvatar Linux Python")
    workspace_root = _text(args.workspace_root, label="ExAvatar Linux workspace")
    runtime_preflight = _text(args.runtime_preflight, label="ExAvatar runtime preflight")
    if not linux_python.startswith("/") or not workspace_root.startswith("/") or not runtime_preflight.startswith("/"):
        raise ExAvatarQuest2PbrAdapterError(
            "ExAvatar Linux Python/workspace/runtime-preflight must be absolute Linux paths"
        )
    request = Path(args.bodyrig_request).expanduser().resolve()
    teacher_root = Path(args.bodyrig_teacher_root).expanduser().resolve()
    output = Path(args.bodyrig_output).expanduser().resolve()
    script = Path(__file__).resolve()
    for path, label in (
        (request, "BodyRig request"),
        (teacher_root, "BodyRig staged teacher root"),
        (output, "BodyRig output root"),
        (script, "BodyRig adapter entrypoint"),
    ):
        if not path.exists():
            raise ExAvatarQuest2PbrAdapterError(f"{label} not found: {path}")
    invocation = [
        args.wsl_exe,
        "-d",
        distribution,
        "--",
        "/usr/bin/env",
        "PYTHONNOUSERSITE=1",
        linux_python,
        _wsl_path(args.wsl_exe, distribution, script),
        "--linux-stage",
        "--workspace-root",
        workspace_root,
        "--runtime-preflight",
        runtime_preflight,
        "--bodyrig-request",
        _wsl_path(args.wsl_exe, distribution, request),
        "--bodyrig-teacher-root",
        _wsl_path(args.wsl_exe, distribution, teacher_root),
        "--bodyrig-output",
        _wsl_path(args.wsl_exe, distribution, output),
        "--bodyrig-adapter",
        args.bodyrig_adapter,
        "--bodyrig-revision",
        args.bodyrig_revision,
        "--bodyrig-student-representation",
        args.bodyrig_student_representation,
        "--bodyrig-student-components",
        args.bodyrig_student_components,
    ]
    completed = subprocess.run(
        invocation,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
        sys.stdout.flush()
    return int(completed.returncode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize an ExAvatar-derived skinned PBR Quest 2 student with explicit eye/hair primitives."
    )
    parser.add_argument("--linux-stage", action="store_true")
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--linux-python", default="/opt/bodyrig-exavatar/bin/python")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--runtime-preflight", required=True)
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-teacher-root", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-student-representation", required=True)
    parser.add_argument("--bodyrig-student-components", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run_linux(args) if args.linux_stage else _run_windows_bridge(args)
    except (OSError, ExAvatarQuest2PbrAdapterError) as exc:
        print(f"BodyRig ExAvatar Quest2 PBR adapter: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
