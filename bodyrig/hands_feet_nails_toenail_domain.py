from __future__ import annotations

import math
import struct
from typing import Any, Mapping

from .fidelity_ab import FidelityAbError, _indices
from .hands_feet_nails_uv_domain_evidence import (
    REGION_JOINT_NAMES,
    WEIGHT_THRESHOLD,
    HandsFeetNailsUvDomainEvidenceError,
    _canonical_mesh,
    _region_domain,
)

FOOT_REGIONS = ("left_foot", "right_foot")
TOE_LABELS = ("big_toe", "toe_2", "toe_3", "toe_4", "small_toe")
FOOT_JOINTS = {
    "left_foot": ("smplx_left_ankle", "smplx_left_foot"),
    "right_foot": ("smplx_right_ankle", "smplx_right_foot"),
}
FOOT_JOINT_WEIGHT_THRESHOLD = 0.08
DISTAL_FRACTION = 0.45
UPPER_FRACTION = 0.65
LANDMARK_HEEL_BLEND = 0.08


class HandsFeetNailsToenailDomainError(RuntimeError):
    pass


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HandsFeetNailsToenailDomainError(f"glTF {name} array is missing")
    return value


def _indexed(document: Mapping[str, Any], array_name: str, index: Any, *, label: str) -> dict[str, Any]:
    array = _array(document, array_name)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(array) or not isinstance(array[index], dict):
        raise HandsFeetNailsToenailDomainError(f"{label} index is invalid")
    return array[index]


def _accessor_values(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
    component_type: int,
    kind: str,
) -> list[tuple[float | int, ...]]:
    accessor = _indexed(document, "accessors", index, label=f"{label} accessor")
    if "sparse" in accessor or accessor.get("componentType") != component_type or accessor.get("type") != kind:
        raise HandsFeetNailsToenailDomainError(f"{label} accessor type is not canonical")
    count = accessor.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise HandsFeetNailsToenailDomainError(f"{label} accessor count is invalid")
    view = _indexed(document, "bufferViews", accessor.get("bufferView"), label=f"{label} bufferView")
    if view.get("buffer", 0) != 0:
        raise HandsFeetNailsToenailDomainError(f"{label} must use GLB buffer 0")
    components = {"VEC2": 2, "VEC3": 3, "VEC4": 4}.get(kind)
    formats = {5123: ("H", 2), 5126: ("f", 4)}
    if components is None or component_type not in formats:
        raise HandsFeetNailsToenailDomainError(f"{label} accessor encoding is unsupported")
    code, width = formats[component_type]
    element_size = components * width
    view_offset = view.get("byteOffset", 0)
    view_length = view.get("byteLength")
    accessor_offset = accessor.get("byteOffset", 0)
    stride = view.get("byteStride", element_size)
    for value, value_label, minimum in (
        (view_offset, "view offset", 0),
        (view_length, "view length", 1),
        (accessor_offset, "accessor offset", 0),
        (stride, "stride", element_size),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise HandsFeetNailsToenailDomainError(f"{label} {value_label} is invalid")
    start = view_offset + accessor_offset
    view_end = view_offset + view_length
    if view_end > len(binary) or start < view_offset:
        raise HandsFeetNailsToenailDomainError(f"{label} accessor exceeds GLB bytes")
    unpacker = struct.Struct("<" + code * components)
    rows: list[tuple[float | int, ...]] = []
    for item in range(count):
        begin = start + item * stride
        end = begin + element_size
        if end > view_end:
            raise HandsFeetNailsToenailDomainError(f"{label} accessor exceeds its bufferView")
        rows.append(tuple(unpacker.unpack(binary[begin:end])))
    return rows


def _body_inputs(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
) -> tuple[
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[int],
    list[str],
]:
    _mesh_index, _skin_index, _primitive_index, primitive, _joint_nodes, joint_names = _canonical_mesh(document)
    attrs = primitive.get("attributes")
    if not isinstance(attrs, Mapping):
        raise HandsFeetNailsToenailDomainError("canonical body primitive attributes are missing")
    try:
        positions = _accessor_values(document, binary, attrs["POSITION"], label="body POSITION", component_type=5126, kind="VEC3")
        uvs = _accessor_values(document, binary, attrs["TEXCOORD_0"], label="body TEXCOORD_0", component_type=5126, kind="VEC2")
        joints = _accessor_values(document, binary, attrs["JOINTS_0"], label="body JOINTS_0", component_type=5123, kind="VEC4")
        weights = _accessor_values(document, binary, attrs["WEIGHTS_0"], label="body WEIGHTS_0", component_type=5126, kind="VEC4")
    except (KeyError, HandsFeetNailsUvDomainEvidenceError) as exc:
        raise HandsFeetNailsToenailDomainError("canonical body position/UV/skinning accessors are invalid") from exc
    if not (len(positions) == len(uvs) == len(joints) == len(weights)):
        raise HandsFeetNailsToenailDomainError("canonical body geometry accessor counts differ")
    try:
        indices = _indices(document, binary, primitive, len(positions))
    except FidelityAbError as exc:
        raise HandsFeetNailsToenailDomainError(str(exc)) from exc
    if len(indices) % 3:
        raise HandsFeetNailsToenailDomainError("canonical body triangle index count is invalid")

    for region in FOOT_REGIONS:
        expected = uv_evidence.get("regions", {}).get(region) if isinstance(uv_evidence.get("regions"), Mapping) else None
        if not isinstance(expected, Mapping):
            raise HandsFeetNailsToenailDomainError(f"{region} UV-domain authority is missing")
        try:
            actual = _region_domain(
                capture_region=region,
                semantic_region=expected["semantic_region"],
                target_names=REGION_JOINT_NAMES[region],
                joint_names=joint_names,
                uvs=uvs,
                joints=joints,
                weights=weights,
            )
        except (KeyError, HandsFeetNailsUvDomainEvidenceError) as exc:
            raise HandsFeetNailsToenailDomainError(f"{region} UV-domain authority is invalid") from exc
        if actual != expected:
            raise HandsFeetNailsToenailDomainError(f"{region} UV domain no longer matches exact package vertices")
    return positions, uvs, joints, weights, indices, joint_names


def _parent_map(document: Mapping[str, Any]) -> dict[int, int]:
    nodes = _array(document, "nodes")
    parents: dict[int, int] = {}
    for parent, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        children = node.get("children", [])
        if not isinstance(children, list):
            raise HandsFeetNailsToenailDomainError("VRM node children are invalid")
        for child in children:
            if isinstance(child, bool) or not isinstance(child, int) or not 0 <= child < len(nodes) or child in parents:
                raise HandsFeetNailsToenailDomainError("VRM skeleton parent graph is invalid")
            parents[child] = parent
    return parents


def _joint_world(document: Mapping[str, Any], name: str) -> tuple[float, float, float]:
    nodes = _array(document, "nodes")
    matches = [index for index, node in enumerate(nodes) if isinstance(node, Mapping) and node.get("name") == name]
    if len(matches) != 1:
        raise HandsFeetNailsToenailDomainError(f"canonical joint {name} is missing or ambiguous")
    parents = _parent_map(document)
    chain: list[int] = []
    cursor = matches[0]
    while True:
        chain.append(cursor)
        if cursor not in parents:
            break
        cursor = parents[cursor]
        if len(chain) > len(nodes):
            raise HandsFeetNailsToenailDomainError("VRM skeleton contains a cycle")
    x = y = z = 0.0
    for index in reversed(chain):
        node = nodes[index]
        if not isinstance(node, Mapping) or any(key in node for key in ("matrix", "rotation", "scale")):
            raise HandsFeetNailsToenailDomainError("toenail v1 requires translation-only SMPL-X rest joints")
        translation = node.get("translation", [0.0, 0.0, 0.0])
        if not isinstance(translation, list) or len(translation) != 3:
            raise HandsFeetNailsToenailDomainError("VRM joint translation is invalid")
        values: list[float] = []
        for raw in translation:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise HandsFeetNailsToenailDomainError("VRM joint translation is non-finite")
            values.append(float(raw))
        x += values[0]
        y += values[1]
        z += values[2]
    return x, y, z


def _centroid(rows: list[tuple[float | int, ...]], triangle: list[int], width: int) -> tuple[float, ...]:
    return tuple(sum(float(rows[index][axis]) for index in triangle) / 3.0 for axis in range(width))


def toenail_triangle_groups(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
) -> dict[str, list[list[int]]]:
    positions, uvs, joints, weights, indices, joint_names = _body_inputs(document, binary, uv_evidence)
    result: dict[str, list[list[int]]] = {}
    claimed: set[int] = set()
    for region in FOOT_REGIONS:
        ankle_name, foot_name = FOOT_JOINTS[region]
        if foot_name not in joint_names:
            raise HandsFeetNailsToenailDomainError(f"{region} foot joint is missing")
        foot_joint = joint_names.index(foot_name)
        expected = uv_evidence["regions"][region]
        target_indices = set(int(value) for value in expected["target_joint_indices"])
        ankle = _joint_world(document, ankle_name)
        foot = _joint_world(document, foot_name)
        dx, dz = foot[0] - ankle[0], foot[2] - ankle[2]
        length = math.hypot(dx, dz)
        if not math.isfinite(length) or length < 1.0e-6:
            raise HandsFeetNailsToenailDomainError(f"{region} ankle-to-foot axis is degenerate")
        forward = (dx / length, dz / length)

        candidates: list[dict[str, Any]] = []
        for offset in range(0, len(indices), 3):
            triangle = indices[offset:offset + 3]
            semantic_membership = [
                sum(
                    float(weight)
                    for joint, weight in zip(joints[vertex], weights[vertex], strict=True)
                    if int(joint) in target_indices
                )
                for vertex in triangle
            ]
            if not all(value >= WEIGHT_THRESHOLD for value in semantic_membership):
                continue
            foot_membership = [
                sum(
                    float(weight)
                    for joint, weight in zip(joints[vertex], weights[vertex], strict=True)
                    if int(joint) == foot_joint
                )
                for vertex in triangle
            ]
            if min(foot_membership) < FOOT_JOINT_WEIGHT_THRESHOLD:
                continue
            position = _centroid(positions, triangle, 3)
            uv = _centroid(uvs, triangle, 2)
            projection = (position[0] - foot[0]) * forward[0] + (position[2] - foot[2]) * forward[1]
            candidates.append({
                "triangle_index": offset // 3,
                "triangle": list(triangle),
                "x": position[0],
                "y": position[1],
                "projection": projection,
                "uv": uv,
            })
        if len(candidates) < 10:
            raise HandsFeetNailsToenailDomainError(f"{region} has too few source-bound distal foot triangles")

        candidates.sort(key=lambda item: (item["projection"], item["triangle_index"]), reverse=True)
        distal_count = max(10, int(math.ceil(len(candidates) * DISTAL_FRACTION)))
        distal = candidates[:distal_count]
        by_height = sorted(float(item["y"]) for item in distal)
        cutoff_index = max(0, min(len(by_height) - 1, int(math.floor((1.0 - UPPER_FRACTION) * (len(by_height) - 1)))))
        y_cutoff = by_height[cutoff_index]
        upper = [item for item in distal if float(item["y"]) >= y_cutoff]
        selected = upper if len(upper) >= 10 else distal
        selected.sort(key=lambda item: (float(item["x"]), int(item["triangle_index"])))
        if region == "right_foot":
            selected.reverse()

        seed_positions = [round(index * (len(selected) - 1) / 4) for index in range(5)]
        if len(set(seed_positions)) != 5:
            raise HandsFeetNailsToenailDomainError(f"{region} cannot resolve five distinct toenail seed domains")
        seeds = [selected[index] for index in seed_positions]
        groups = {label: [list(seed["triangle"])] for label, seed in zip(TOE_LABELS, seeds, strict=True)}
        centers = {label: float(seed["x"]) for label, seed in zip(TOE_LABELS, seeds, strict=True)}
        seed_ids = {int(seed["triangle_index"]) for seed in seeds}
        for item in selected:
            triangle_index = int(item["triangle_index"])
            if triangle_index in seed_ids:
                continue
            label = min(TOE_LABELS, key=lambda candidate: (abs(float(item["x"]) - centers[candidate]), TOE_LABELS.index(candidate)))
            groups[label].append(list(item["triangle"]))
        for label in TOE_LABELS:
            key = f"{region}_{label}"
            triangles = groups[label]
            if not triangles:
                raise HandsFeetNailsToenailDomainError(f"{key} produced no source-bound triangles")
            for triangle in triangles:
                triangle_index = next(
                    int(item["triangle_index"])
                    for item in selected
                    if item["triangle"] == triangle
                )
                if triangle_index in claimed:
                    raise HandsFeetNailsToenailDomainError("toenail geometry selection overlaps between labels")
                claimed.add(triangle_index)
            result[key] = triangles
    if len(result) != 10:
        raise HandsFeetNailsToenailDomainError("toenail domain must resolve exactly ten nail plates")
    return result


def toe_source_landmarks(projection: Mapping[str, Any]) -> dict[str, dict[str, float | bool]]:
    landmarks = projection.get("landmarks")
    if not isinstance(landmarks, Mapping):
        raise HandsFeetNailsToenailDomainError("foot projection landmarks are missing")

    def point(name: str) -> tuple[float, float, float]:
        raw = landmarks.get(name)
        if not isinstance(raw, Mapping):
            raise HandsFeetNailsToenailDomainError(f"foot projection lacks {name} landmark")
        values: list[float] = []
        for field in ("x_norm", "y_norm", "confidence"):
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise HandsFeetNailsToenailDomainError(f"{name} {field} is invalid")
            values.append(float(value))
        if not (0.0 <= values[0] <= 1.0 and 0.0 <= values[1] <= 1.0 and 0.0 <= values[2] <= 1.0):
            raise HandsFeetNailsToenailDomainError(f"{name} landmark escaped normalized bounds")
        return values[0], values[1], values[2]

    big = point("big_toe")
    small = point("small_toe")
    heel = point("heel")
    result: dict[str, dict[str, float | bool]] = {}
    for index, label in enumerate(TOE_LABELS):
        t = index / 4.0
        tip_x = big[0] * (1.0 - t) + small[0] * t
        tip_y = big[1] * (1.0 - t) + small[1] * t
        x = tip_x * (1.0 - LANDMARK_HEEL_BLEND) + heel[0] * LANDMARK_HEEL_BLEND
        y = tip_y * (1.0 - LANDMARK_HEEL_BLEND) + heel[1] * LANDMARK_HEEL_BLEND
        result[label] = {
            "x_norm": round(x, 8),
            "y_norm": round(y, 8),
            "confidence": round(min(big[2], small[2]), 6),
            "interpolated": label not in {"big_toe", "small_toe"},
        }
    return result
