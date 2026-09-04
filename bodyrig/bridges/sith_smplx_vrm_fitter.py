#!/usr/bin/env python
"""High-fidelity BodyRig fitter: SiTH textured mesh + SMPL-X fit -> skinned VRM 1.0.

This adapter is intentionally standalone. It runs inside the pinned SiTH/SMPL-X
Python environment behind BodyRig's external-fitter file boundary. It does not
import BodyRig core and never serializes SMPL-X model assets into the portable
avatar.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import math
import os
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

ADAPTER = "sith-smplx-vrm"
REVISION = "1"
REQUEST_FORMAT = "bodyrig-avatar-fit-request"
RESULT_FORMAT = "bodyrig-avatar-fit-result"
RECON_FORMAT = "bodyrig-sith-reconstruction"
VRM_EXTENSION = "VRMC_vrm"
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

# First 55 SMPL-X LBS joints in kinematic order.
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
}


class FitterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FitterError(f"{label} not found")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FitterError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FitterError(f"{label} must be an object")
    return value


def _finite_vector(value: Any, *, field: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise FitterError(f"SiTH fit {field} must contain exactly {length} values")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise FitterError(f"SiTH fit {field} contains a non-finite value")
        result.append(float(item))
    return result


def _fit_params(path: Path) -> dict[str, list[float]]:
    value = _read_json(path, label="SiTH fit parameters")
    if set(value) != set(FIT_PARAM_LENGTHS):
        raise FitterError("SiTH fit parameter fields do not match v1")
    result = {
        field: _finite_vector(value[field], field=field, length=length)
        for field, length in FIT_PARAM_LENGTHS.items()
    }
    if not 0.05 <= result["scale"][0] <= 20.0:
        raise FitterError("SiTH fit scale is outside the accepted range")
    return result


def _validate_request(path: Path, adapter: str, revision: str) -> dict[str, Any]:
    request = _read_json(path, label="BodyRig fitter request")
    required = {"format", "version", "name", "bodyprint", "visual_identity"}
    if set(request) != required:
        raise FitterError("BodyRig fitter request fields do not match v1")
    if request["format"] != REQUEST_FORMAT or request["version"] != 1:
        raise FitterError("unsupported BodyRig fitter request")
    if adapter != ADAPTER or revision != REVISION:
        raise FitterError("BodyRig fitter adapter/revision mismatch")
    name = request["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise FitterError("BodyRig avatar name is invalid")
    identity = request["visual_identity"]
    if not isinstance(identity, dict):
        raise FitterError("BodyRig visual identity is missing")
    if identity.get("format") != "bodyrig-visual-identity" or identity.get("version") != 1:
        raise FitterError("unsupported BodyRig visual identity")
    track = identity.get("subject_track_id")
    if not isinstance(track, str) or not track or len(track) > 160:
        raise FitterError("BodyRig visual identity track id is invalid")
    privacy = identity.get("privacy")
    if privacy != {"contains_source_media": False, "contains_biometric_template": False}:
        raise FitterError("BodyRig visual identity privacy boundary is invalid")
    return request


def _leaf(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise FitterError(f"{label} must be a filename")
    cleaned = value.strip().strip('"')
    if not cleaned or Path(cleaned).name != cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise FitterError(f"{label} must be a leaf filename")
    return cleaned


def _validate_workspace(workspace: Path, request: dict[str, Any]) -> dict[str, Path]:
    stage = workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    reconstruction = _read_json(reconstruction_path, label="SiTH reconstruction evidence")
    required = {
        "format", "version", "prepared_input_sha256", "subject_track_id",
        "sith_revision", "diffusion_model_sha256", "diffusion_model_file_count",
        "diffusion_model_byte_count", "seed", "hallucination", "reconstruction",
    }
    if set(reconstruction) != required:
        raise FitterError("SiTH reconstruction evidence fields do not match v1")
    if reconstruction["format"] != RECON_FORMAT or reconstruction["version"] != 1:
        raise FitterError("unsupported SiTH reconstruction evidence")
    if reconstruction["subject_track_id"] != request["visual_identity"]["subject_track_id"]:
        raise FitterError("SiTH reconstruction subject does not match BodyRig visual identity")

    details = reconstruction["reconstruction"]
    detail_fields = {
        "grid_size", "save_uv", "smplx_obj_sha256", "fit_params_sha256",
        "back_image_sha256", "mesh_obj_sha256", "mesh_mtl_sha256",
        "mesh_texture_name", "mesh_texture_sha256",
    }
    if not isinstance(details, dict) or set(details) != detail_fields:
        raise FitterError("SiTH reconstruction detail fields do not match v1")
    if details["grid_size"] != 300 or details["save_uv"] is not True:
        raise FitterError("SiTH reconstruction is not the pinned UV profile")

    texture_name = _leaf(details["mesh_texture_name"], label="SiTH texture reference")
    paths = {
        "stage": stage,
        "smplx_obj": stage / "smplx" / "000_smplx.obj",
        "fit_params": stage / "smplx" / "000_fit.json",
        "mesh_obj": stage / "meshes" / "000_reco.obj",
        "mesh_mtl": stage / "meshes" / "000.mtl",
        "texture": stage / "meshes" / texture_name,
    }
    hashes = {
        "smplx_obj": details["smplx_obj_sha256"],
        "fit_params": details["fit_params_sha256"],
        "mesh_obj": details["mesh_obj_sha256"],
        "mesh_mtl": details["mesh_mtl_sha256"],
        "texture": details["mesh_texture_sha256"],
    }
    for key, path in paths.items():
        if key == "stage":
            continue
        if not path.is_file():
            raise FitterError(f"SiTH {key} artifact is missing")
        expected = hashes[key]
        if not isinstance(expected, str) or not SHA_RE.fullmatch(expected) or _sha256(path) != expected:
            raise FitterError(f"SiTH {key} artifact hash mismatch")
    if not paths["texture"].read_bytes().startswith(PNG_SIGNATURE):
        raise FitterError("SiTH texture is not PNG")
    _fit_params(paths["fit_params"])
    return paths


def _parse_positions(path: Path) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise FitterError("OBJ is not valid UTF-8 text") from exc
    for line in lines:
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            raise FitterError("OBJ vertex is malformed")
        try:
            xyz = tuple(float(parts[index]) for index in range(1, 4))
        except ValueError as exc:
            raise FitterError("OBJ vertex is non-numeric") from exc
        if not all(math.isfinite(value) for value in xyz):
            raise FitterError("OBJ vertex is non-finite")
        vertices.append(xyz)  # type: ignore[arg-type]
    if len(vertices) < 3:
        raise FitterError("OBJ contains too few vertices")
    return vertices


def _obj_index(raw: str, count: int, *, label: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise FitterError(f"OBJ {label} index is invalid") from exc
    if value <= 0 or value > count:
        raise FitterError(f"OBJ {label} index is outside the supported positive range")
    return value - 1


def _parse_textured_obj(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[float, float]], list[list[tuple[int, int]]]]:
    positions: list[tuple[float, float, float]] = []
    texcoords: list[tuple[float, float]] = []
    raw_faces: list[list[tuple[str, str]]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise FitterError("SiTH textured OBJ is not valid UTF-8 text") from exc
    for line in lines:
        if line.startswith("v "):
            parts = line.split()
            if len(parts) < 4:
                raise FitterError("SiTH textured OBJ vertex is malformed")
            xyz = tuple(float(parts[index]) for index in range(1, 4))
            if not all(math.isfinite(value) for value in xyz):
                raise FitterError("SiTH textured OBJ vertex is non-finite")
            positions.append(xyz)  # type: ignore[arg-type]
        elif line.startswith("vt "):
            parts = line.split()
            if len(parts) < 3:
                raise FitterError("SiTH textured OBJ UV is malformed")
            uv = (float(parts[1]), float(parts[2]))
            if not all(math.isfinite(value) for value in uv):
                raise FitterError("SiTH textured OBJ UV is non-finite")
            texcoords.append(uv)
        elif line.startswith("f "):
            tokens = line.split()[1:]
            if len(tokens) != 3:
                raise FitterError("SiTH textured OBJ must contain triangular faces only")
            face: list[tuple[str, str]] = []
            for token in tokens:
                fields = token.split("/")
                if len(fields) < 2 or not fields[0] or not fields[1]:
                    raise FitterError("SiTH textured OBJ face must bind position and UV")
                face.append((fields[0], fields[1]))
            raw_faces.append(face)
    if len(positions) < 3 or len(texcoords) < 3 or not raw_faces:
        raise FitterError("SiTH textured OBJ is incomplete")
    faces: list[list[tuple[int, int]]] = []
    for face in raw_faces:
        faces.append([
            (_obj_index(vertex, len(positions), label="vertex"), _obj_index(uv, len(texcoords), label="UV"))
            for vertex, uv in face
        ])
    return positions, texcoords, faces


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


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
    return PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b"")


def _pad4(data: bytes, pad: bytes) -> bytes:
    return data + pad * ((-len(data)) % 4)


def _glb(document: dict[str, Any], binary: bytes) -> bytes:
    json_chunk = _pad4(json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"), b" ")
    bin_chunk = _pad4(binary, b"\x00")
    chunks = struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    if bin_chunk:
        chunks += struct.pack("<I4s", len(bin_chunk), b"BIN\x00") + bin_chunk
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _build_vrm(
    *,
    np: Any,
    name: str,
    rest_positions: Any,
    texcoords: list[tuple[float, float]],
    faces: list[list[tuple[int, int]]],
    joints4: Any,
    weights4: Any,
    rest_joints: Any,
    parents: list[int],
    texture_png: bytes,
    quality: dict[str, float],
) -> tuple[bytes, bytes]:
    if len(parents) != len(SMPLX_JOINT_NAMES) or rest_joints.shape != (len(SMPLX_JOINT_NAMES), 3):
        raise FitterError("SMPL-X joint topology does not match BodyRig v1")

    vertex_map: dict[tuple[int, int], int] = {}
    positions_out: list[Any] = []
    uv_out: list[tuple[float, float]] = []
    joints_out: list[Any] = []
    weights_out: list[Any] = []
    indices: list[int] = []
    for face in faces:
        for vertex_index, uv_index in face:
            key = (vertex_index, uv_index)
            mapped = vertex_map.get(key)
            if mapped is None:
                mapped = len(positions_out)
                vertex_map[key] = mapped
                positions_out.append(rest_positions[vertex_index])
                u, v = texcoords[uv_index]
                uv_out.append((float(u), float(1.0 - v)))
                joints_out.append(joints4[vertex_index])
                weights_out.append(weights4[vertex_index])
            indices.append(mapped)

    positions_arr = np.asarray(positions_out, dtype=np.float32)
    uv_arr = np.asarray(uv_out, dtype=np.float32)
    joints_arr = np.asarray(joints_out, dtype=np.uint16)
    weights_arr = np.asarray(weights_out, dtype=np.float32)
    indices_arr = np.asarray(indices, dtype=np.uint32)
    if positions_arr.shape[0] < 3 or indices_arr.size < 3:
        raise FitterError("rigged mesh contains too little geometry")

    normals = np.zeros_like(positions_arr)
    tri = indices_arr.reshape(-1, 3)
    for a, b, c in tri:
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

    joint_nodes: list[dict[str, Any]] = []
    for index, joint_name in enumerate(SMPLX_JOINT_NAMES):
        parent = int(parents[index])
        if index == 0:
            translation = rest_joints[index]
        else:
            if parent < 0 or parent >= index:
                raise FitterError("SMPL-X parent topology is invalid")
            translation = rest_joints[index] - rest_joints[parent]
        joint_nodes.append({
            "name": f"smplx_{joint_name}",
            "translation": [float(value) for value in translation],
        })
    for index in range(1, len(joint_nodes)):
        parent = int(parents[index])
        joint_nodes[parent].setdefault("children", []).append(index)

    mesh_node = len(joint_nodes)
    nodes = [*joint_nodes, {"name": name, "mesh": 0, "skin": 0}]
    human_bones = {bone: {"node": index} for bone, index in VRM_HUMANOID.items()}

    inverse_bind: list[float] = []
    for joint in rest_joints:
        x, y, z = (float(value) for value in joint)
        inverse_bind.extend((
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            -x, -y, -z, 1.0,
        ))
    ibm_arr = np.asarray(inverse_bind, dtype=np.float32).reshape(-1, 16)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def add_accessor(raw: bytes, *, component: int, count: int, kind: str, target: int | None = None, minimum: list[float] | None = None, maximum: list[float] | None = None) -> int:
        view = add_view(raw, target=target)
        accessor: dict[str, Any] = {"bufferView": view, "componentType": component, "count": count, "type": kind}
        if minimum is not None:
            accessor["min"] = minimum
        if maximum is not None:
            accessor["max"] = maximum
        accessors.append(accessor)
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
    normal_accessor = add_accessor(normals.astype("<f4", copy=False).tobytes(), component=5126, count=len(normals), kind="VEC3", target=34962)
    uv_accessor = add_accessor(uv_arr.astype("<f4", copy=False).tobytes(), component=5126, count=len(uv_arr), kind="VEC2", target=34962)
    joints_accessor = add_accessor(joints_arr.astype("<u2", copy=False).tobytes(), component=5123, count=len(joints_arr), kind="VEC4", target=34962)
    weights_accessor = add_accessor(weights_arr.astype("<f4", copy=False).tobytes(), component=5126, count=len(weights_arr), kind="VEC4", target=34962)
    index_accessor = add_accessor(indices_arr.astype("<u4", copy=False).tobytes(), component=5125, count=int(indices_arr.size), kind="SCALAR", target=34963)
    ibm_accessor = add_accessor(ibm_arr.astype("<f4", copy=False).tobytes(), component=5126, count=len(rest_joints), kind="MAT4")
    texture_view = add_view(texture_png)
    thumbnail = _thumbnail_png()
    thumbnail_view = add_view(thumbnail)

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "BodyRig sith-smplx-vrm/1"},
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
                    "thumbnailImage": 1,
                },
                "humanoid": {"humanBones": human_bones},
            }
        },
        "scene": 0,
        "scenes": [{"nodes": [0, mesh_node]}],
        "nodes": nodes,
        "meshes": [{
            "name": "BodyRigSourceDerivedMesh",
            "primitives": [{
                "attributes": {
                    "POSITION": pos_accessor,
                    "NORMAL": normal_accessor,
                    "TEXCOORD_0": uv_accessor,
                    "JOINTS_0": joints_accessor,
                    "WEIGHTS_0": weights_accessor,
                },
                "indices": index_accessor,
                "material": 0,
                "mode": 4,
            }],
        }],
        "skins": [{
            "name": "SMPLX",
            "inverseBindMatrices": ibm_accessor,
            "skeleton": 0,
            "joints": list(range(len(SMPLX_JOINT_NAMES))),
        }],
        "materials": [{
            "name": "BodyRigSourceDerivedMaterial",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.9,
            },
        }],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "images": [
            {"name": "BodyRigAvatarTexture", "bufferView": texture_view, "mimeType": "image/png"},
            {"name": "BodyRigThumbnail", "bufferView": thumbnail_view, "mimeType": "image/png"},
        ],
        "textures": [{"sampler": 0, "source": 0}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "bodyrig": {
                "placeholder": False,
                "sourceDerivedVisualIdentity": True,
                "fitter": {"adapter": ADAPTER, "revision": REVISION},
                "rigTransfer": {
                    "method": "nearest-smplx-vertex-lbs-inverse",
                    "nearestDistanceP95": round(float(quality["nearest_p95"]), 6),
                    "nearestDistanceMax": round(float(quality["nearest_max"]), 6),
                },
            }
        },
    }
    return _glb(document, bytes(binary)), thumbnail


def _rig_mesh(paths: dict[str, Path], *, model_dir: str, name: str) -> tuple[bytes, bytes, dict[str, float]]:
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
        from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints
    except ImportError as exc:
        raise FitterError("numpy, torch and smplx are required in the SiTH fitter environment") from exc
    if not torch.cuda.is_available():
        raise FitterError("SiTH SMPL-X VRM fitting requires CUDA")

    device = torch.device("cuda")
    params = _fit_params(paths["fit_params"])
    donor_obj = np.asarray(_parse_positions(paths["smplx_obj"]), dtype=np.float32)
    reco_positions_list, texcoords, faces = _parse_textured_obj(paths["mesh_obj"])
    reco_obj = np.asarray(reco_positions_list, dtype=np.float32)

    try:
        model = SMPLX(
            model_path=model_dir,
            gender="male",
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise FitterError("failed to load the licensed SMPL-X male model") from exc
    model.eval()
    if int(model.lbs_weights.shape[0]) != len(donor_obj) or int(model.lbs_weights.shape[1]) != len(SMPLX_JOINT_NAMES):
        raise FitterError("SMPL-X model topology does not match SiTH fitted OBJ")
    parents = [int(value) for value in model.parents.detach().cpu().tolist()]
    if len(parents) != len(SMPLX_JOINT_NAMES) or parents[0] != -1:
        raise FitterError("SMPL-X parent topology is incompatible with BodyRig v1")

    def tensor(field: str, width: int) -> Any:
        return torch.tensor(params[field], dtype=torch.float32, device=device).view(1, width)

    betas = tensor("betas", 10)
    expression = tensor("expression", 10)
    global_orient = tensor("global_orient", 3)
    body_pose = tensor("body_pose", 63)
    left_hand = tensor("left_hand_pose", 45)
    right_hand = tensor("right_hand_pose", 45)
    jaw = tensor("jaw_pose", 3)
    leye = tensor("leye_pose", 3)
    reye = tensor("reye_pose", 3)
    transl = tensor("transl", 3)
    scale = float(params["scale"][0])

    with torch.no_grad():
        output = model(
            betas=betas,
            expression=expression,
            global_orient=global_orient,
            body_pose=body_pose,
            left_hand_pose=left_hand,
            right_hand_pose=right_hand,
            jaw_pose=jaw,
            leye_pose=leye,
            reye_pose=reye,
            transl=transl,
            return_verts=True,
        )
        posed_model = output.vertices[0] * scale
        donor_tensor = torch.tensor(donor_obj, dtype=torch.float32, device=device)
        delta = torch.linalg.vector_norm(posed_model - donor_tensor, dim=1)
        if float(delta.max().item()) > 0.005 or float(torch.sqrt(torch.mean(delta * delta)).item()) > 0.001:
            raise FitterError("SiTH fit parameters do not numerically reproduce the fitted SMPL-X OBJ")

        shape_components = torch.cat([betas, expression], dim=-1)
        shapedirs = torch.cat([model.shapedirs, model.expr_dirs], dim=-1)
        v_shaped = model.v_template + blend_shapes(shape_components, shapedirs)
        rest_joints = vertices2joints(model.J_regressor, v_shaped)

        full_pose = torch.cat([
            global_orient.view(1, 1, 3),
            body_pose.view(1, 21, 3),
            jaw.view(1, 1, 3),
            leye.view(1, 1, 3),
            reye.view(1, 1, 3),
            left_hand.view(1, 15, 3),
            right_hand.view(1, 15, 3),
        ], dim=1).reshape(1, -1)
        full_pose = full_pose + model.pose_mean
        rot_mats = batch_rodrigues(full_pose.view(-1, 3)).view(1, -1, 3, 3)
        ident = torch.eye(3, dtype=torch.float32, device=device)
        pose_feature = (rot_mats[:, 1:] - ident).reshape(1, -1)
        pose_offsets = torch.matmul(pose_feature, model.posedirs).view(1, -1, 3)
        _, transforms = batch_rigid_transform(rot_mats, rest_joints, model.parents, dtype=torch.float32)

        reco = torch.tensor(reco_obj, dtype=torch.float32, device=device)
        donor = posed_model
        weights = model.lbs_weights
        rest_chunks: list[Any] = []
        joint_chunks: list[Any] = []
        weight_chunks: list[Any] = []
        nearest_distances: list[Any] = []
        chunk_size = 768
        for start in range(0, int(reco.shape[0]), chunk_size):
            chunk = reco[start:start + chunk_size]
            distances = torch.cdist(chunk.unsqueeze(0), donor.unsqueeze(0)).squeeze(0)
            nearest_distance, nearest = torch.min(distances, dim=1)
            nearest_distances.append(nearest_distance.detach().cpu())
            full_weights = weights[nearest]
            transform = torch.matmul(full_weights, transforms[0].reshape(len(SMPLX_JOINT_NAMES), 16)).view(-1, 4, 4)
            model_space = chunk / scale - transl[0]
            homogeneous = torch.cat([model_space, torch.ones((len(chunk), 1), device=device)], dim=1).unsqueeze(-1)
            try:
                inverse = torch.linalg.inv(transform)
            except RuntimeError as exc:
                raise FitterError("SMPL-X blended skin transform is singular") from exc
            unskinned = torch.matmul(inverse, homogeneous)[:, :3, 0]
            rest = unskinned - pose_offsets[0, nearest]
            top_weight, top_joint = torch.topk(full_weights, k=4, dim=1)
            totals = top_weight.sum(dim=1, keepdim=True)
            if bool(torch.any(totals <= 1e-8).item()):
                raise FitterError("SMPL-X skin weights contain an empty influence set")
            top_weight = top_weight / totals
            rest_chunks.append(rest.detach().cpu())
            joint_chunks.append(top_joint.detach().cpu())
            weight_chunks.append(top_weight.detach().cpu())

        rest_positions = torch.cat(rest_chunks, dim=0).numpy()
        joints4 = torch.cat(joint_chunks, dim=0).numpy()
        weights4 = torch.cat(weight_chunks, dim=0).numpy()
        nearest_all = torch.cat(nearest_distances).numpy()
        nearest_p95 = float(np.quantile(nearest_all, 0.95))
        nearest_max = float(np.max(nearest_all))
        if not math.isfinite(nearest_p95) or not math.isfinite(nearest_max):
            raise FitterError("SMPL-X nearest-surface quality is non-finite")
        if nearest_p95 > 0.30 or nearest_max > 0.85:
            raise FitterError(
                f"SiTH mesh is too far from the fitted SMPL-X surface (p95={nearest_p95:.4f}, max={nearest_max:.4f})"
            )

    quality = {"nearest_p95": nearest_p95, "nearest_max": nearest_max}
    texture = paths["texture"].read_bytes()
    return (*_build_vrm(
        np=np,
        name=name,
        rest_positions=rest_positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        rest_joints=rest_joints[0].detach().cpu().numpy(),
        parents=parents,
        texture_png=texture,
        quality=quality,
    ), quality)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smplx-model-dir", required=True, help="Absolute Linux path containing licensed SMPL-X model files")
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args()

    try:
        if not args.smplx_model_dir.startswith("/"):
            raise FitterError("SMPL-X model directory must be an absolute Linux path")
        request_path = Path(args.bodyrig_request).resolve()
        workspace = Path(args.bodyrig_workspace).resolve()
        output = Path(args.bodyrig_output).resolve()
        if not workspace.is_dir() or not output.is_dir() or any(output.iterdir()):
            raise FitterError("BodyRig fitter boundary directories are invalid or output is not empty")
        request = _validate_request(request_path, args.bodyrig_adapter, args.bodyrig_revision)
        paths = _validate_workspace(workspace, request)
        avatar, thumbnail, _quality = _rig_mesh(paths, model_dir=args.smplx_model_dir, name=request["name"].strip())
        avatar_path = output / "avatar.vrm"
        thumbnail_path = output / "thumbnail.png"
        avatar_path.write_bytes(avatar)
        thumbnail_path.write_bytes(thumbnail)
        result = {
            "format": RESULT_FORMAT,
            "version": 1,
            "adapter": ADAPTER,
            "revision": REVISION,
            "visual_identity": "source-derived",
            "avatar_sha256": hashlib.sha256(avatar).hexdigest(),
            "thumbnail_sha256": hashlib.sha256(thumbnail).hexdigest(),
        }
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        if {path.name for path in output.iterdir()} != {"avatar.vrm", "thumbnail.png", "result.json"}:
            raise FitterError("BodyRig fitter output boundary contains unexpected artifacts")
        print("BodyRig SiTH SMPL-X VRM fitter: PASS")
        return 0
    except Exception as exc:
        print(f"BodyRig SiTH SMPL-X VRM fitter: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
