from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .hands_feet_nails_fingernail_geometry_candidate import (
    HandsFeetNailsFingernailGeometryError,
    _body_geometry_inputs,
)


FORMAT = "bodyrig-photoreal-p3-quest2-teacher-hair-component"
VERSION = 1

MIN_FACE_COUNT = 32
MIN_DISTANCE_BODY_RATIO = 0.008
SEED_DISTANCE_BODY_RATIO = 0.006
MIN_Y_BODY_RATIO = 0.60
SEED_Y_BODY_RATIO = 0.79
SHORT_HAIR_MIN_DISTANCE_BODY_RATIO = 0.003
SHORT_HAIR_SEED_DISTANCE_BODY_RATIO = 0.0025
SHORT_HAIR_MIN_Y_BODY_RATIO = 0.72
SHORT_HAIR_SEED_Y_BODY_RATIO = 0.80
MIN_HEAD_FOOTPRINT_BODY_RATIO = 0.035
MIN_VERTICAL_SPAN_BODY_RATIO = 0.012
MAX_OFFSET_BODY_RATIO = 0.20

NODE_NAME = "BodyRigP3QuestTeacherHair"
MESH_NAME = "BodyRigP3QuestTeacherHairMesh"
MATERIAL_NAME = "BodyRigP3TeacherHairPBR"
IMAGE_NAME = "BodyRigP3TeacherHairBake"


class PhotorealP3Quest2HairComponentError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3Quest2HairComponentError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealP3Quest2HairComponentError(f"{label} is invalid")
    return result


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise PhotorealP3Quest2HairComponentError("hair metric has no values")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) for value in ordered):
        raise PhotorealP3Quest2HairComponentError("hair metric is non-finite")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _body_height(positions: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    if len(positions) < 16:
        raise PhotorealP3Quest2HairComponentError("hair donor geometry is incomplete")
    ys = [_finite(row[1], label="hair donor Y") for row in positions if len(row) >= 3]
    if len(ys) != len(positions):
        raise PhotorealP3Quest2HairComponentError("hair donor position width is invalid")
    y_min = min(ys)
    y_max = max(ys)
    height = y_max - y_min
    if not math.isfinite(height) or height <= 1e-6:
        raise PhotorealP3Quest2HairComponentError("hair donor height is invalid")
    return y_min, y_max, height


def select_teacher_hair_faces(
    *,
    donor_positions: Sequence[Sequence[float]],
    donor_faces: Sequence[Sequence[int]],
    outward_offsets: Sequence[float],
) -> dict[str, Any]:
    if len(outward_offsets) != len(donor_positions):
        raise PhotorealP3Quest2HairComponentError(
            "teacher hair offset vector does not match donor geometry"
        )
    y_min, _y_max, body_height = _body_height(donor_positions)
    offsets = []
    for raw in outward_offsets:
        value = _finite(raw, label="teacher hair outward offset")
        if value < 0.0 or value > body_height * MAX_OFFSET_BODY_RATIO:
            raise PhotorealP3Quest2HairComponentError(
                "teacher hair outward offset is outside the bounded envelope"
            )
        offsets.append(value)

    donor = []
    for row in donor_positions:
        if len(row) < 3:
            raise PhotorealP3Quest2HairComponentError("hair donor position width is invalid")
        point = tuple(_finite(row[i], label="hair donor coordinate") for i in range(3))
        donor.append(point)

    head = [
        point
        for point in donor
        if (point[1] - y_min) / body_height >= 0.80
    ]
    if len(head) < 8:
        raise PhotorealP3Quest2HairComponentError("hair donor head region is too small")
    center_x = _quantile([point[0] for point in head], 0.5)
    center_z = _quantile([point[2] for point in head], 0.5)
    head_radius = _quantile(
        [math.hypot(point[0] - center_x, point[2] - center_z) for point in head],
        0.95,
    )
    search_radius = min(max(head_radius * 1.85, body_height * 0.08), body_height * 0.25)

    normalized_y = [(point[1] - y_min) / body_height for point in donor]
    radial = [math.hypot(point[0] - center_x, point[2] - center_z) for point in donor]

    faces: list[tuple[int, int, int]] = []
    for raw in donor_faces:
        if len(raw) != 3:
            raise PhotorealP3Quest2HairComponentError("hair donor topology is not triangular")
        triangle = tuple(int(value) for value in raw)
        if any(value < 0 or value >= len(donor) for value in triangle):
            raise PhotorealP3Quest2HairComponentError("hair donor face escapes vertex universe")
        faces.append(triangle)

    def run_pass(
        *,
        mode: str,
        minimum_distance_ratio: float,
        seed_distance_ratio: float,
        minimum_y_ratio: float,
        seed_y_ratio: float,
    ) -> dict[str, Any] | None:
        minimum_distance = body_height * minimum_distance_ratio
        seed_distance = body_height * seed_distance_ratio
        candidate_vertices = {
            index
            for index in range(len(donor))
            if normalized_y[index] >= minimum_y_ratio
            and radial[index] <= search_radius
            and offsets[index] >= minimum_distance
        }
        seed_vertices = {
            index
            for index in range(len(donor))
            if normalized_y[index] >= seed_y_ratio
            and radial[index] <= search_radius
            and offsets[index] >= seed_distance
        }

        candidate_faces: list[int] = []
        seed_faces: list[int] = []
        for face_index, triangle in enumerate(faces):
            in_candidate = sum(vertex in candidate_vertices for vertex in triangle)
            mean_y = sum(normalized_y[vertex] for vertex in triangle) / 3.0
            if in_candidate >= 2 and mean_y >= minimum_y_ratio:
                candidate_faces.append(face_index)
                if any(vertex in seed_vertices for vertex in triangle):
                    seed_faces.append(face_index)
        if not seed_faces:
            return None

        by_vertex: dict[int, list[int]] = {}
        candidate_set = set(candidate_faces)
        seed_set = set(seed_faces)
        for face_index in candidate_faces:
            for vertex in faces[face_index]:
                by_vertex.setdefault(vertex, []).append(face_index)

        components: list[tuple[set[int], int]] = []
        visited_seed_faces: set[int] = set()
        for seed_face in sorted(seed_faces):
            if seed_face in visited_seed_faces:
                continue
            component = {seed_face}
            queue: deque[int] = deque([seed_face])
            while queue:
                face_index = queue.popleft()
                for vertex in faces[face_index]:
                    for neighbor in by_vertex.get(vertex, []):
                        if neighbor in candidate_set and neighbor not in component:
                            component.add(neighbor)
                            queue.append(neighbor)
            retained_seed_count = len(component.intersection(seed_set))
            visited_seed_faces.update(component.intersection(seed_set))
            components.append((component, retained_seed_count))

        selected, retained_seed_count = max(
            components,
            key=lambda item: (len(item[0]), item[1], -min(item[0])),
        )
        selected_faces = sorted(selected)
        selected_vertices = sorted(
            {vertex for face_index in selected_faces for vertex in faces[face_index]}
        )
        selected_offsets = [offsets[index] for index in selected_vertices]
        xs = [donor[index][0] for index in selected_vertices]
        ys = [donor[index][1] + offsets[index] for index in selected_vertices]
        zs = [donor[index][2] for index in selected_vertices]
        footprint = max(max(xs) - min(xs), max(zs) - min(zs)) / body_height
        vertical_span = (max(ys) - min(ys)) / body_height

        return {
            "selection_mode": mode,
            "selected_face_indices": selected_faces,
            "selected_vertex_indices": selected_vertices,
            "selected_face_count": len(selected_faces),
            "selected_vertex_count": len(selected_vertices),
            "seed_face_count": retained_seed_count,
            "body_height": body_height,
            "head_center_x": center_x,
            "head_center_z": center_z,
            "head_search_radius": search_radius,
            "outward_offset_p50": _quantile(selected_offsets, 0.50),
            "outward_offset_p95": _quantile(selected_offsets, 0.95),
            "outward_offset_max": max(selected_offsets),
            "head_footprint_span_body_ratio": footprint,
            "vertical_span_body_ratio": vertical_span,
            "minimum_distance_body_ratio": minimum_distance_ratio,
            "seed_distance_body_ratio": seed_distance_ratio,
            "minimum_y_body_ratio": minimum_y_ratio,
            "seed_y_body_ratio": seed_y_ratio,
        }

    def adequate(value: dict[str, Any] | None) -> bool:
        return bool(
            value is not None
            and value["selected_face_count"] >= MIN_FACE_COUNT
            and value["head_footprint_span_body_ratio"] >= MIN_HEAD_FOOTPRINT_BODY_RATIO
            and value["vertical_span_body_ratio"] >= MIN_VERTICAL_SPAN_BODY_RATIO
        )

    strict = run_pass(
        mode="strict-teacher-shell",
        minimum_distance_ratio=MIN_DISTANCE_BODY_RATIO,
        seed_distance_ratio=SEED_DISTANCE_BODY_RATIO,
        minimum_y_ratio=MIN_Y_BODY_RATIO,
        seed_y_ratio=SEED_Y_BODY_RATIO,
    )
    if adequate(strict):
        return strict  # type: ignore[return-value]

    fallback = run_pass(
        mode="short-hair-teacher-fallback",
        minimum_distance_ratio=SHORT_HAIR_MIN_DISTANCE_BODY_RATIO,
        seed_distance_ratio=SHORT_HAIR_SEED_DISTANCE_BODY_RATIO,
        minimum_y_ratio=SHORT_HAIR_MIN_Y_BODY_RATIO,
        seed_y_ratio=SHORT_HAIR_SEED_Y_BODY_RATIO,
    )
    candidate = fallback if fallback is not None else strict
    if candidate is None:
        raise PhotorealP3Quest2HairComponentError(
            "accepted ExAvatar teacher exposes no connected geometric hair seed above the fitted head"
        )
    if candidate["selected_face_count"] < MIN_FACE_COUNT:
        raise PhotorealP3Quest2HairComponentError(
            "accepted ExAvatar teacher hair shell is too small"
        )
    if candidate["head_footprint_span_body_ratio"] < MIN_HEAD_FOOTPRINT_BODY_RATIO:
        raise PhotorealP3Quest2HairComponentError(
            "accepted ExAvatar teacher hair shell footprint is too narrow"
        )
    if candidate["vertical_span_body_ratio"] < MIN_VERTICAL_SPAN_BODY_RATIO:
        raise PhotorealP3Quest2HairComponentError(
            "accepted ExAvatar teacher hair shell vertical span is too small"
        )
    return candidate


def _validate_envelope_shape(value: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    faces = value.get("selected_faces")
    body_face_count = value.get("body_face_count")
    if isinstance(body_face_count, bool) or not isinstance(body_face_count, int) or body_face_count < 1:
        raise PhotorealP3Quest2HairComponentError("teacher hair body face count is invalid")
    if not isinstance(faces, list) or len(faces) < MIN_FACE_COUNT:
        raise PhotorealP3Quest2HairComponentError("teacher hair face envelope is incomplete")
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in faces:
        if not isinstance(raw, Mapping) or set(raw) != {"face_index", "corner_offsets"}:
            raise PhotorealP3Quest2HairComponentError("teacher hair face envelope fields mismatch")
        face_index = raw.get("face_index")
        if (
            isinstance(face_index, bool)
            or not isinstance(face_index, int)
            or face_index < 0
            or face_index >= body_face_count
            or face_index in seen
        ):
            raise PhotorealP3Quest2HairComponentError("teacher hair face index is invalid/repeated")
        offsets = raw.get("corner_offsets")
        if not isinstance(offsets, list) or len(offsets) != 3:
            raise PhotorealP3Quest2HairComponentError("teacher hair corner offsets are invalid")
        clean_offsets = [_finite(item, label="teacher hair corner offset") for item in offsets]
        if any(item < 0.0 for item in clean_offsets):
            raise PhotorealP3Quest2HairComponentError("teacher hair corner offset is negative")
        normalized.append({"face_index": face_index, "corner_offsets": clean_offsets})
        seen.add(face_index)
    normalized.sort(key=lambda item: item["face_index"])
    return normalized, body_face_count


def graft_teacher_hair_component(
    avatar_vrm: bytes,
    *,
    teacher_basecolor_png: bytes,
    teacher_basecolor_sha256: str,
    hair_envelope: Mapping[str, Any],
    source_eye_receipt_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    if not teacher_basecolor_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PhotorealP3Quest2HairComponentError("teacher hair basecolor is not PNG")
    if _sha256_bytes(teacher_basecolor_png) != teacher_basecolor_sha256:
        raise PhotorealP3Quest2HairComponentError("teacher hair basecolor digest mismatch")
    if (
        len(source_eye_receipt_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in source_eye_receipt_sha256)
    ):
        raise PhotorealP3Quest2HairComponentError("source eye receipt SHA-256 is invalid")

    selected_faces, envelope_face_count = _validate_envelope_shape(hair_envelope)
    try:
        import numpy as np
    except ImportError as exc:
        raise PhotorealP3Quest2HairComponentError(
            f"numpy is required for teacher hair graft: {exc}"
        ) from exc

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
    except (PbrMaterialError, HandsFeetNailsFingernailGeometryError) as exc:
        raise PhotorealP3Quest2HairComponentError(
            f"Quest2 eye student VRM is incompatible with hair graft: {exc}"
        ) from exc

    if len(indices) % 3 or len(indices) // 3 != envelope_face_count:
        raise PhotorealP3Quest2HairComponentError(
            "teacher hair envelope topology differs from Quest2 student body"
        )

    hair_positions: list[list[float]] = []
    hair_normals: list[list[float]] = []
    hair_uvs: list[list[float]] = []
    hair_joints: list[list[int]] = []
    hair_weights: list[list[float]] = []
    hair_indices: list[int] = []
    for selected in selected_faces:
        face_index = selected["face_index"]
        corner_offsets = selected["corner_offsets"]
        for corner in range(3):
            source_vertex = int(indices[face_index * 3 + corner])
            if source_vertex < 0 or source_vertex >= len(positions):
                raise PhotorealP3Quest2HairComponentError(
                    "teacher hair source face escapes student vertex universe"
                )
            position = np.asarray(positions[source_vertex], dtype=np.float64)
            normal = np.asarray(normals[source_vertex], dtype=np.float64)
            length = float(np.linalg.norm(normal))
            if not math.isfinite(length) or length <= 1e-8:
                raise PhotorealP3Quest2HairComponentError("teacher hair source normal is invalid")
            normal = normal / length
            offset = float(corner_offsets[corner])
            displaced = position + normal * offset
            hair_positions.append([float(value) for value in displaced])
            hair_normals.append([float(value) for value in normal])
            hair_uvs.append([float(value) for value in uvs[source_vertex]])
            hair_joints.append([int(value) for value in joints[source_vertex]])
            raw_weights = [float(value) for value in weights[source_vertex]]
            total = sum(raw_weights)
            if not math.isfinite(total) or total <= 1e-8 or any(value < 0.0 for value in raw_weights):
                raise PhotorealP3Quest2HairComponentError("teacher hair source skin weights are invalid")
            hair_weights.append([value / total for value in raw_weights])
            hair_indices.append(len(hair_indices))

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
        raw = document.get(key)
        if not isinstance(raw, list):
            raise PhotorealP3Quest2HairComponentError(
                f"teacher hair base VRM lacks glTF {key} array"
            )
        arrays[key] = raw
    if len(arrays["buffers"]) != 1 or not arrays["samplers"]:
        raise PhotorealP3Quest2HairComponentError("teacher hair base VRM buffer/sampler contract is invalid")
    if not arrays["scenes"] or not isinstance(arrays["scenes"][0], dict):
        raise PhotorealP3Quest2HairComponentError("teacher hair base VRM scene is invalid")
    scene_nodes = arrays["scenes"][0].get("nodes")
    if not isinstance(scene_nodes, list):
        raise PhotorealP3Quest2HairComponentError("teacher hair base VRM scene nodes are invalid")

    extras = document.setdefault("extras", {})
    if not isinstance(extras, dict):
        raise PhotorealP3Quest2HairComponentError("teacher hair base VRM extras are invalid")
    bodyrig = extras.setdefault("bodyrig", {})
    if not isinstance(bodyrig, dict):
        raise PhotorealP3Quest2HairComponentError("teacher hair BodyRig metadata is invalid")
    if "p3QuestTeacherHairComponent" in bodyrig:
        raise PhotorealP3Quest2HairComponentError("teacher hair component is already present")

    binary_out = bytearray(binary)

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary_out) % 4:
            binary_out.append(0)
        offset = len(binary_out)
        binary_out.extend(raw)
        item: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(raw),
        }
        if target is not None:
            item["target"] = target
        arrays["bufferViews"].append(item)
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
            raise PhotorealP3Quest2HairComponentError("teacher hair accessor type is unsupported")
        view = add_view(raw, target=target)
        item: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": len(array),
            "type": kind,
        }
        if bounds:
            item["min"] = [float(value) for value in array.min(axis=0)]
            item["max"] = [float(value) for value in array.max(axis=0)]
        arrays["accessors"].append(item)
        return len(arrays["accessors"]) - 1

    pos = np.asarray(hair_positions, dtype=np.float32)
    norm = np.asarray(hair_normals, dtype=np.float32)
    uv = np.asarray(hair_uvs, dtype=np.float32)
    joint = np.asarray(hair_joints, dtype=np.uint16)
    weight = np.asarray(hair_weights, dtype=np.float32)
    idx = np.asarray(hair_indices, dtype=np.uint32)

    image_view = add_view(teacher_basecolor_png)
    arrays["images"].append(
        {"name": IMAGE_NAME, "bufferView": image_view, "mimeType": "image/png"}
    )
    arrays["textures"].append({"sampler": 0, "source": len(arrays["images"]) - 1})
    texture_index = len(arrays["textures"]) - 1
    arrays["materials"].append(
        {
            "name": MATERIAL_NAME,
            "doubleSided": True,
            "alphaMode": "OPAQUE",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": texture_index},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.72,
            },
        }
    )
    material_index = len(arrays["materials"]) - 1

    primitive = {
        "attributes": {
            "POSITION": add_accessor(pos, component=5126, kind="VEC3", target=34962, bounds=True),
            "NORMAL": add_accessor(norm, component=5126, kind="VEC3", target=34962),
            "TEXCOORD_0": add_accessor(uv, component=5126, kind="VEC2", target=34962),
            "JOINTS_0": add_accessor(joint, component=5123, kind="VEC4", target=34962),
            "WEIGHTS_0": add_accessor(weight, component=5126, kind="VEC4", target=34962),
        },
        "indices": add_accessor(idx, component=5125, kind="SCALAR", target=34963),
        "material": material_index,
        "mode": 4,
        "extras": {"bodyrigP3HairRole": "teacher-derived-head-hair-shell"},
    }
    arrays["meshes"].append({"name": MESH_NAME, "primitives": [primitive]})
    arrays["nodes"].append(
        {"name": NODE_NAME, "mesh": len(arrays["meshes"]) - 1, "skin": 0}
    )
    scene_nodes.append(len(arrays["nodes"]) - 1)

    metadata: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "sourceEyeReceiptSha256": source_eye_receipt_sha256,
        "teacherBasecolorSha256": teacher_basecolor_sha256,
        "teacherHairEnvelopeSha256": hair_envelope.get("hair_envelope_sha256"),
        "selectionMode": hair_envelope.get("selection_mode"),
        "hairFaceCount": len(selected_faces),
        "hairVertexCount": len(hair_positions),
        "sourceDerived": True,
        "generativeGeometry": False,
        "bodyTopologyModified": False,
        "separateRuntimePrimitive": True,
        "teacherDerivedAppearance": True,
        "physicalSilhouetteReviewRequired": True,
        "teacherDerivedHairComponentImplemented": True,
        "separateEyelashGeometryClaimed": False,
        "runtimeAcceptanceAuthority": False,
        "photorealAcceptanceAuthority": False,
        "productionActivation": False,
    }
    bodyrig["p3QuestTeacherHairComponent"] = metadata
    arrays["buffers"][0]["byteLength"] = len(binary_out)
    output = _write_glb(document, bytes(binary_out))
    metadata["outputVrmSha256"] = _sha256_bytes(output)
    return output, metadata
