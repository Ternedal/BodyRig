from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import (
    PbrMaterialError,
    _read_glb,
    _write_glb,
)
from .hands_feet_nails_fingernail_geometry_candidate import (
    HandsFeetNailsFingernailGeometryError,
    _body_geometry_inputs,
)


FORMAT = "bodyrig-photoreal-p3-quest2-specialized-eye-component"
VERSION = 1
LEFT_EYE_JOINT = 23
RIGHT_EYE_JOINT = 24
MIN_EYE_FACE_COUNT = 8
VERTEX_EYE_WEIGHT_THRESHOLD = 0.35
FACE_EYE_WEIGHT_THRESHOLD = 0.45
SURFACE_SCALE = 1.0015
CORNEA_SCALE = 1.012

NODE_NAME = "BodyRigP3QuestEyeComponent"
MESH_NAME = "BodyRigP3QuestEyeMesh"
SOURCE_MATERIAL_NAME = "BodyRigP3TeacherEyeSurface"
CORNEA_MATERIAL_NAME = "BodyRigP3QuestCornea"
SOURCE_IMAGE_NAME = "BodyRigP3TeacherEyeBake"

PRIMITIVE_ROLES = (
    "left_surface",
    "left_cornea",
    "right_surface",
    "right_cornea",
)


class PhotorealP3Quest2EyeComponentError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _joint_weight(
    joints: Sequence[float | int],
    weights: Sequence[float | int],
    *,
    joint_index: int,
) -> float:
    if len(joints) != 4 or len(weights) != 4:
        raise PhotorealP3Quest2EyeComponentError(
            "eye source skinning tuple width is invalid"
        )
    total = 0.0
    for raw_joint, raw_weight in zip(joints, weights):
        joint = int(raw_joint)
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0:
            raise PhotorealP3Quest2EyeComponentError(
                "eye source skinning weight is invalid"
            )
        if joint == joint_index:
            total += weight
    return total


def select_eye_triangles(
    *,
    indices: Sequence[int],
    joints: Sequence[Sequence[float | int]],
    weights: Sequence[Sequence[float | int]],
    joint_index: int,
    minimum_faces: int = MIN_EYE_FACE_COUNT,
) -> list[int]:
    if joint_index < 0:
        raise PhotorealP3Quest2EyeComponentError(
            "eye joint index is invalid"
        )
    if len(indices) < 3 or len(indices) % 3:
        raise PhotorealP3Quest2EyeComponentError(
            "eye source triangle index universe is invalid"
        )
    if len(joints) != len(weights) or len(joints) < 3:
        raise PhotorealP3Quest2EyeComponentError(
            "eye source skinning universe is invalid"
        )
    selected: list[int] = []
    for face_index in range(len(indices) // 3):
        triangle = [
            int(indices[face_index * 3 + offset])
            for offset in range(3)
        ]
        if any(vertex < 0 or vertex >= len(joints) for vertex in triangle):
            raise PhotorealP3Quest2EyeComponentError(
                "eye source triangle index escapes vertex universe"
            )
        values = [
            _joint_weight(
                joints[vertex],
                weights[vertex],
                joint_index=joint_index,
            )
            for vertex in triangle
        ]
        if (
            all(value >= VERTEX_EYE_WEIGHT_THRESHOLD for value in values)
            and sum(values) / 3.0 >= FACE_EYE_WEIGHT_THRESHOLD
        ):
            selected.append(face_index)
    if len(selected) < minimum_faces:
        raise PhotorealP3Quest2EyeComponentError(
            f"eye geometry is insufficiently isolated by LBS authority: "
            f"joint={joint_index}, faces={len(selected)}"
        )
    return selected


def _eye_arrays(
    np: Any,
    *,
    positions: Sequence[Sequence[float | int]],
    normals: Sequence[Sequence[float | int]],
    uvs: Sequence[Sequence[float | int]],
    joints: Sequence[Sequence[float | int]],
    weights: Sequence[Sequence[float | int]],
    indices: Sequence[int],
    selected_faces: Sequence[int],
    scale: float,
) -> tuple[Any, Any, Any, Any, Any, Any]:
    vertices = sorted(
        {
            int(indices[face_index * 3 + offset])
            for face_index in selected_faces
            for offset in range(3)
        }
    )
    if len(vertices) < 3:
        raise PhotorealP3Quest2EyeComponentError(
            "eye component has too few unique vertices"
        )
    raw_positions = np.asarray(
        [[float(value) for value in positions[index]] for index in vertices],
        dtype=np.float32,
    )
    center = raw_positions.mean(axis=0)
    scaled_positions = center[None, :] + (
        raw_positions - center[None, :]
    ) * float(scale)
    normal_array = np.asarray(
        [[float(value) for value in normals[index]] for index in vertices],
        dtype=np.float32,
    )
    lengths = np.linalg.norm(normal_array, axis=1)
    if bool(np.any(~np.isfinite(lengths))) or bool(np.any(lengths <= 1e-8)):
        raise PhotorealP3Quest2EyeComponentError(
            "eye component contains invalid source normals"
        )
    normal_array = normal_array / lengths[:, None]
    uv_array = np.asarray(
        [[float(value) for value in uvs[index]] for index in vertices],
        dtype=np.float32,
    )
    joint_array = np.asarray(
        [[int(value) for value in joints[index]] for index in vertices],
        dtype=np.uint16,
    )
    weight_array = np.asarray(
        [[float(value) for value in weights[index]] for index in vertices],
        dtype=np.float32,
    )
    totals = weight_array.sum(axis=1, keepdims=True)
    if (
        bool(np.any(~np.isfinite(weight_array)))
        or bool(np.any(weight_array < 0.0))
        or bool(np.any(totals <= 1e-8))
    ):
        raise PhotorealP3Quest2EyeComponentError(
            "eye component source skin weights are invalid"
        )
    weight_array = weight_array / totals

    remap = {source: target for target, source in enumerate(vertices)}
    local_indices: list[int] = []
    for face_index in selected_faces:
        for offset in range(3):
            local_indices.append(
                remap[int(indices[face_index * 3 + offset])]
            )
    index_array = np.asarray(local_indices, dtype=np.uint32)
    return (
        scaled_positions,
        normal_array,
        uv_array,
        joint_array,
        weight_array,
        index_array,
    )


def _append_component(
    *,
    document: dict[str, Any],
    binary_bytes: bytes,
    left_surface: tuple[Any, Any, Any, Any, Any, Any],
    left_cornea: tuple[Any, Any, Any, Any, Any, Any],
    right_surface: tuple[Any, Any, Any, Any, Any, Any],
    right_cornea: tuple[Any, Any, Any, Any, Any, Any],
    teacher_basecolor_png: bytes,
    metadata: Mapping[str, Any],
) -> bytes:
    arrays: dict[str, list[Any]] = {}
    for key in (
        "bufferViews",
        "accessors",
        "images",
        "textures",
        "materials",
        "meshes",
        "nodes",
        "scenes",
        "samplers",
        "buffers",
    ):
        value = document.get(key)
        if not isinstance(value, list):
            raise PhotorealP3Quest2EyeComponentError(
                f"eye component base VRM lacks glTF {key} array"
            )
        arrays[key] = value
    if len(arrays["buffers"]) != 1:
        raise PhotorealP3Quest2EyeComponentError(
            "eye component requires one GLB binary buffer"
        )
    if not arrays["samplers"]:
        raise PhotorealP3Quest2EyeComponentError(
            "eye component base VRM exposes no sampler"
        )
    if (
        not arrays["scenes"]
        or not isinstance(arrays["scenes"][0], dict)
        or not isinstance(arrays["scenes"][0].get("nodes"), list)
    ):
        raise PhotorealP3Quest2EyeComponentError(
            "eye component base VRM scene is invalid"
        )

    extras = document.setdefault("extras", {})
    if not isinstance(extras, dict):
        raise PhotorealP3Quest2EyeComponentError(
            "eye component base VRM extras are invalid"
        )
    bodyrig = extras.setdefault("bodyrig", {})
    if not isinstance(bodyrig, dict):
        raise PhotorealP3Quest2EyeComponentError(
            "eye component base VRM BodyRig metadata is invalid"
        )
    if "p3QuestEyeComponent" in bodyrig:
        raise PhotorealP3Quest2EyeComponentError(
            "specialized eye component is already present"
        )
    if any(
        isinstance(node, dict) and node.get("name") == NODE_NAME
        for node in arrays["nodes"]
    ):
        raise PhotorealP3Quest2EyeComponentError(
            "specialized eye node name is already present"
        )

    binary = bytearray(binary_bytes)

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(raw),
        }
        if target is not None:
            view["target"] = target
        arrays["bufferViews"].append(view)
        return len(arrays["bufferViews"]) - 1

    def add_accessor(
        array: Any,
        *,
        component: int,
        kind: str,
        target: int | None = None,
        bounds: bool = False,
    ) -> int:
        if component == 5126:
            raw = array.astype("<f4", copy=False).tobytes()
        elif component == 5123:
            raw = array.astype("<u2", copy=False).tobytes()
        elif component == 5125:
            raw = array.astype("<u4", copy=False).tobytes()
        else:
            raise PhotorealP3Quest2EyeComponentError(
                "eye component accessor type is unsupported"
            )
        view = add_view(raw, target=target)
        accessor: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": len(array),
            "type": kind,
        }
        if bounds:
            accessor["min"] = [
                float(value) for value in array.min(axis=0)
            ]
            accessor["max"] = [
                float(value) for value in array.max(axis=0)
            ]
        arrays["accessors"].append(accessor)
        return len(arrays["accessors"]) - 1

    image_view = add_view(teacher_basecolor_png)
    arrays["images"].append(
        {
            "name": SOURCE_IMAGE_NAME,
            "bufferView": image_view,
            "mimeType": "image/png",
        }
    )
    arrays["textures"].append(
        {
            "sampler": 0,
            "source": len(arrays["images"]) - 1,
        }
    )
    eye_texture = len(arrays["textures"]) - 1

    arrays["materials"].append(
        {
            "name": SOURCE_MATERIAL_NAME,
            "doubleSided": False,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": eye_texture},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.36,
            },
        }
    )
    surface_material = len(arrays["materials"]) - 1
    arrays["materials"].append(
        {
            "name": CORNEA_MATERIAL_NAME,
            "doubleSided": False,
            "alphaMode": "BLEND",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 0.11],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.04,
            },
        }
    )
    cornea_material = len(arrays["materials"]) - 1

    primitives: list[dict[str, Any]] = []
    for role, values in zip(
        PRIMITIVE_ROLES,
        (left_surface, left_cornea, right_surface, right_cornea),
    ):
        pos, normal, uv, joints, weights, indices = values
        material = (
            cornea_material
            if role.endswith("cornea")
            else surface_material
        )
        primitives.append(
            {
                "attributes": {
                    "POSITION": add_accessor(
                        pos,
                        component=5126,
                        kind="VEC3",
                        target=34962,
                        bounds=True,
                    ),
                    "NORMAL": add_accessor(
                        normal,
                        component=5126,
                        kind="VEC3",
                        target=34962,
                    ),
                    "TEXCOORD_0": add_accessor(
                        uv,
                        component=5126,
                        kind="VEC2",
                        target=34962,
                    ),
                    "JOINTS_0": add_accessor(
                        joints,
                        component=5123,
                        kind="VEC4",
                        target=34962,
                    ),
                    "WEIGHTS_0": add_accessor(
                        weights,
                        component=5126,
                        kind="VEC4",
                        target=34962,
                    ),
                },
                "indices": add_accessor(
                    indices,
                    component=5125,
                    kind="SCALAR",
                    target=34963,
                ),
                "material": material,
                "mode": 4,
                "extras": {"bodyrigP3EyeRole": role},
            }
        )

    arrays["meshes"].append(
        {"name": MESH_NAME, "primitives": primitives}
    )
    arrays["nodes"].append(
        {
            "name": NODE_NAME,
            "mesh": len(arrays["meshes"]) - 1,
            "skin": 0,
        }
    )
    arrays["scenes"][0]["nodes"].append(len(arrays["nodes"]) - 1)
    bodyrig["p3QuestEyeComponent"] = dict(metadata)
    arrays["buffers"][0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary))


def graft_specialized_eye_component(
    avatar_vrm: bytes,
    *,
    teacher_basecolor_png: bytes,
    source_candidate_receipt_sha256: str,
    teacher_basecolor_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    if not teacher_basecolor_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PhotorealP3Quest2EyeComponentError(
            "teacher eye basecolor is not PNG"
        )
    if _sha256_bytes(teacher_basecolor_png) != teacher_basecolor_sha256:
        raise PhotorealP3Quest2EyeComponentError(
            "teacher eye basecolor digest mismatch"
        )
    if (
        len(source_candidate_receipt_sha256) != 64
        or any(
            char not in "0123456789abcdef"
            for char in source_candidate_receipt_sha256
        )
    ):
        raise PhotorealP3Quest2EyeComponentError(
            "source candidate receipt SHA-256 is invalid"
        )

    try:
        document, binary = _read_glb(avatar_vrm)
        (
            _primitive,
            positions,
            normals,
            uvs,
            joints,
            weights,
            indices,
            _joint_names,
        ) = _body_geometry_inputs(document, binary)
    except (
        PbrMaterialError,
        HandsFeetNailsFingernailGeometryError,
    ) as exc:
        raise PhotorealP3Quest2EyeComponentError(
            f"Quest2 base student VRM is incompatible with eye graft: {exc}"
        ) from exc

    left = select_eye_triangles(
        indices=indices,
        joints=joints,
        weights=weights,
        joint_index=LEFT_EYE_JOINT,
    )
    right = select_eye_triangles(
        indices=indices,
        joints=joints,
        weights=weights,
        joint_index=RIGHT_EYE_JOINT,
    )
    if set(left) & set(right):
        raise PhotorealP3Quest2EyeComponentError(
            "left/right specialized eye triangles overlap"
        )

    try:
        import numpy as np
    except ImportError as exc:
        raise PhotorealP3Quest2EyeComponentError(
            f"numpy is required for specialized eye graft: {exc}"
        ) from exc

    left_surface = _eye_arrays(
        np,
        positions=positions,
        normals=normals,
        uvs=uvs,
        joints=joints,
        weights=weights,
        indices=indices,
        selected_faces=left,
        scale=SURFACE_SCALE,
    )
    left_cornea = _eye_arrays(
        np,
        positions=positions,
        normals=normals,
        uvs=uvs,
        joints=joints,
        weights=weights,
        indices=indices,
        selected_faces=left,
        scale=CORNEA_SCALE,
    )
    right_surface = _eye_arrays(
        np,
        positions=positions,
        normals=normals,
        uvs=uvs,
        joints=joints,
        weights=weights,
        indices=indices,
        selected_faces=right,
        scale=SURFACE_SCALE,
    )
    right_cornea = _eye_arrays(
        np,
        positions=positions,
        normals=normals,
        uvs=uvs,
        joints=joints,
        weights=weights,
        indices=indices,
        selected_faces=right,
        scale=CORNEA_SCALE,
    )

    metadata: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "sourceCandidateReceiptSha256": source_candidate_receipt_sha256,
        "teacherBasecolorSha256": teacher_basecolor_sha256,
        "leftEyeJointIndex": LEFT_EYE_JOINT,
        "rightEyeJointIndex": RIGHT_EYE_JOINT,
        "leftEyeFaceCount": len(left),
        "rightEyeFaceCount": len(right),
        "surfaceScale": SURFACE_SCALE,
        "corneaScale": CORNEA_SCALE,
        "teacherDerivedAppearance": True,
        "separateRuntimePrimitives": True,
        "cornealMaterialApplied": True,
        "eyelashStatus": "teacher-derived-hair-component-pending",
        "physicalFaceCloseupReviewRequired": True,
        "specializedEyeComponentImplemented": True,
        "runtimeAcceptanceAuthority": False,
        "photorealAcceptanceAuthority": False,
        "productionActivation": False,
    }
    eye_vrm = _append_component(
        document=document,
        binary_bytes=binary,
        left_surface=left_surface,
        left_cornea=left_cornea,
        right_surface=right_surface,
        right_cornea=right_cornea,
        teacher_basecolor_png=teacher_basecolor_png,
        metadata=metadata,
    )
    metadata["outputVrmSha256"] = _sha256_bytes(eye_vrm)
    return eye_vrm, metadata


def write_eye_component(
    *,
    avatar_vrm: str | Path,
    teacher_basecolor_png: str | Path,
    source_candidate_receipt_sha256: str,
    output_vrm: str | Path,
    output_receipt: str | Path,
) -> dict[str, Any]:
    avatar_path = Path(avatar_vrm).expanduser().resolve()
    basecolor_path = Path(teacher_basecolor_png).expanduser().resolve()
    output_vrm_path = Path(output_vrm).expanduser().resolve()
    receipt_path = Path(output_receipt).expanduser().resolve()
    if output_vrm_path.exists() or receipt_path.exists():
        raise PhotorealP3Quest2EyeComponentError(
            "specialized eye outputs are create-only"
        )
    if not avatar_path.is_file() or avatar_path.is_symlink():
        raise PhotorealP3Quest2EyeComponentError(
            "Quest2 base student VRM is missing/not regular"
        )
    if not basecolor_path.is_file() or basecolor_path.is_symlink():
        raise PhotorealP3Quest2EyeComponentError(
            "teacher-derived basecolor is missing/not regular"
        )
    basecolor = basecolor_path.read_bytes()
    output, metadata = graft_specialized_eye_component(
        avatar_path.read_bytes(),
        teacher_basecolor_png=basecolor,
        source_candidate_receipt_sha256=source_candidate_receipt_sha256,
        teacher_basecolor_sha256=_sha256_bytes(basecolor),
    )
    output_vrm_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    output_vrm_path.write_bytes(output)
    receipt = {
        **metadata,
        "inputVrmSha256": _sha256_bytes(avatar_path.read_bytes()),
        "teacherBasecolorSha256": _sha256_bytes(basecolor),
        "outputVrmSha256": _sha256_bytes(output),
    }
    receipt_path.write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt
