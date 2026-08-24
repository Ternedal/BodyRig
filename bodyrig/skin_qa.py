from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bodyrig.avatar import AvatarError, validate_vrm1
from bodyrig.package import validate_package

FORMAT = "bodyrig-skin-qa"
VERSION = 1
MAX_ANALYZED_VERTICES = 50_000
SUSPICIOUS_WEIGHT = 0.10
SEVERE_WEIGHT = 0.35
STRONG_REGION_MARGIN_RATIO = 1.35
STRONG_REGION_MARGIN_SCALE = 0.02


class SkinQaError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise SkinQaError("skin QA: invalid GLB magic")
    if int.from_bytes(data[4:8], "little") != 2:
        raise SkinQaError("skin QA: GLB version must be 2")
    if int.from_bytes(data[8:12], "little") != len(data):
        raise SkinQaError("skin QA: GLB declared length mismatch")

    document: dict[str, Any] | None = None
    binary = b""
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise SkinQaError("skin QA: truncated GLB chunk header")
        length = int.from_bytes(data[offset : offset + 4], "little")
        kind = data[offset + 4 : offset + 8]
        offset += 8
        end = offset + length
        if end > len(data):
            raise SkinQaError("skin QA: truncated GLB chunk")
        chunk = data[offset:end]
        offset = end
        if kind == b"JSON":
            if document is not None:
                raise SkinQaError("skin QA: multiple JSON chunks")
            try:
                value = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SkinQaError("skin QA: invalid glTF JSON") from exc
            if not isinstance(value, dict):
                raise SkinQaError("skin QA: glTF JSON must be an object")
            document = value
        elif kind == b"BIN\x00":
            if binary:
                raise SkinQaError("skin QA: multiple BIN chunks")
            binary = chunk
    if document is None or not binary:
        raise SkinQaError("skin QA: GLB must contain JSON and BIN chunks")
    return document, binary


_COMPONENTS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _accessor(document: dict[str, Any], binary: bytes, index: int, *, label: str) -> list[tuple[float | int, ...]]:
    accessors = document.get("accessors")
    views = document.get("bufferViews")
    if not isinstance(accessors, list) or not isinstance(views, list) or not 0 <= index < len(accessors):
        raise SkinQaError(f"skin QA: invalid {label} accessor")
    accessor = accessors[index]
    if not isinstance(accessor, dict) or "sparse" in accessor:
        raise SkinQaError(f"skin QA: unsupported {label} accessor")
    view_index = accessor.get("bufferView")
    component_type = accessor.get("componentType")
    count = accessor.get("count")
    kind = accessor.get("type")
    if isinstance(view_index, bool) or not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise SkinQaError(f"skin QA: {label} accessor has invalid bufferView")
    if component_type not in _COMPONENTS or kind not in _TYPE_WIDTH:
        raise SkinQaError(f"skin QA: {label} accessor type is unsupported")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise SkinQaError(f"skin QA: {label} accessor count is invalid")
    view = views[view_index]
    if not isinstance(view, dict) or view.get("buffer", 0) != 0:
        raise SkinQaError(f"skin QA: {label} accessor must use embedded buffer 0")

    fmt, component_size = _COMPONENTS[component_type]
    width = _TYPE_WIDTH[kind]
    element_size = component_size * width
    byte_stride = view.get("byteStride", element_size)
    if isinstance(byte_stride, bool) or not isinstance(byte_stride, int) or byte_stride < element_size:
        raise SkinQaError(f"skin QA: {label} accessor byteStride is invalid")
    base = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    view_length = view.get("byteLength")
    if isinstance(view_length, bool) or not isinstance(view_length, int) or view_length < 0:
        raise SkinQaError(f"skin QA: {label} bufferView byteLength is invalid")
    if base < 0 or base + (count - 1) * byte_stride + element_size > len(binary):
        raise SkinQaError(f"skin QA: {label} accessor exceeds BIN chunk")

    unpack = struct.Struct("<" + fmt * width)
    result: list[tuple[float | int, ...]] = []
    for item in range(count):
        start = base + item * byte_stride
        result.append(unpack.unpack_from(binary, start))
    return result


def _matrix_identity() -> list[list[float]]:
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _matrix_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4)] for row in range(4)]


def _local_matrix(node: dict[str, Any]) -> list[list[float]]:
    matrix = node.get("matrix")
    if matrix is not None:
        if not isinstance(matrix, list) or len(matrix) != 16:
            raise SkinQaError("skin QA: node matrix must contain 16 values")
        values = [float(value) for value in matrix]
        if not all(math.isfinite(value) for value in values):
            raise SkinQaError("skin QA: node matrix contains non-finite value")
        return [[values[col * 4 + row] for col in range(4)] for row in range(4)]

    translation = node.get("translation", [0.0, 0.0, 0.0])
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    if not isinstance(translation, list) or len(translation) != 3:
        raise SkinQaError("skin QA: node translation is invalid")
    if not isinstance(rotation, list) or len(rotation) != 4:
        raise SkinQaError("skin QA: node rotation is invalid")
    if not isinstance(scale, list) or len(scale) != 3:
        raise SkinQaError("skin QA: node scale is invalid")
    t = [float(value) for value in translation]
    q = [float(value) for value in rotation]
    s = [float(value) for value in scale]
    if not all(math.isfinite(value) for value in t + q + s):
        raise SkinQaError("skin QA: node transform contains non-finite value")
    length = math.sqrt(sum(value * value for value in q))
    if length <= 1e-12:
        raise SkinQaError("skin QA: node rotation quaternion is empty")
    x, y, z, w = (value / length for value in q)
    rotation_matrix = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    scale_matrix = _matrix_identity()
    scale_matrix[0][0], scale_matrix[1][1], scale_matrix[2][2] = s
    translation_matrix = _matrix_identity()
    translation_matrix[0][3], translation_matrix[1][3], translation_matrix[2][3] = t
    return _matrix_mul(translation_matrix, _matrix_mul(rotation_matrix, scale_matrix))


def _parents(nodes: list[Any]) -> dict[int, int]:
    parents: dict[int, int] = {}
    for parent, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise SkinQaError("skin QA: glTF node must be an object")
        children = raw.get("children", [])
        if not isinstance(children, list):
            raise SkinQaError("skin QA: node children must be an array")
        for child in children:
            if isinstance(child, bool) or not isinstance(child, int) or not 0 <= child < len(nodes):
                raise SkinQaError("skin QA: node child index is invalid")
            if child in parents:
                raise SkinQaError("skin QA: node has multiple parents")
            parents[child] = parent
    return parents


def _world_matrices(nodes: list[Any]) -> list[list[list[float]]]:
    parents = _parents(nodes)
    cache: dict[int, list[list[float]]] = {}
    visiting: set[int] = set()

    def resolve(index: int) -> list[list[float]]:
        if index in cache:
            return cache[index]
        if index in visiting:
            raise SkinQaError("skin QA: node hierarchy contains a cycle")
        visiting.add(index)
        node = nodes[index]
        local = _local_matrix(node)
        parent = parents.get(index)
        world = local if parent is None else _matrix_mul(resolve(parent), local)
        visiting.remove(index)
        cache[index] = world
        return world

    return [resolve(index) for index in range(len(nodes))]


def _region(name: str) -> str:
    lowered = name.strip().lower().replace("-", "_")
    if lowered.startswith("left_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "left_leg"
        return "left_arm"
    if lowered.startswith("right_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "right_leg"
        return "right_arm"
    return "torso"


def _point_segment_distance(point: tuple[float, float, float], a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    ab = tuple(b[i] - a[i] for i in range(3))
    ap = tuple(point[i] - a[i] for i in range(3))
    denominator = sum(value * value for value in ab)
    if denominator <= 1e-16:
        return math.sqrt(sum(value * value for value in ap))
    t = max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / denominator))
    closest = tuple(a[i] + t * ab[i] for i in range(3))
    return math.sqrt(sum((point[i] - closest[i]) ** 2 for i in range(3)))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _forbidden(region: str) -> set[str]:
    if region == "left_arm":
        return {"right_arm", "left_leg", "right_leg"}
    if region == "right_arm":
        return {"left_arm", "left_leg", "right_leg"}
    if region == "left_leg":
        return {"right_leg", "left_arm", "right_arm"}
    if region == "right_leg":
        return {"left_leg", "left_arm", "right_arm"}
    return set()


def analyze_vrm_skin(
    avatar: bytes,
    *,
    package_sha256: str,
    body_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    try:
        document = validate_vrm1(avatar)
    except AvatarError as exc:
        raise SkinQaError(str(exc)) from exc
    document, binary = _parse_glb(avatar)

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict) or bodyrig.get("placeholder") is not False or bodyrig.get("sourceDerivedVisualIdentity") is not True:
        raise SkinQaError("skin QA: avatar is not source-derived high fidelity")
    fitter = bodyrig.get("fitter")
    transfer = bodyrig.get("rigTransfer")
    if fitter != {"adapter": "sith-smplx-vrm", "revision": "1"}:
        raise SkinQaError("skin QA: avatar was not produced by sith-smplx-vrm v1")
    if not isinstance(transfer, dict) or transfer.get("method") != "nearest-smplx-vertex-lbs-inverse":
        raise SkinQaError("skin QA: unsupported rig transfer method")
    nearest_p95 = transfer.get("nearestDistanceP95")
    nearest_max = transfer.get("nearestDistanceMax")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0 for value in (nearest_p95, nearest_max)):
        raise SkinQaError("skin QA: rig transfer distance evidence is invalid")

    meshes = document.get("meshes")
    skins = document.get("skins")
    nodes = document.get("nodes")
    if not isinstance(meshes, list) or not isinstance(skins, list) or len(skins) != 1 or not isinstance(nodes, list):
        raise SkinQaError("skin QA: expected one skinned high-fidelity mesh")

    primitive: dict[str, Any] | None = None
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        for candidate in mesh.get("primitives", []):
            if not isinstance(candidate, dict):
                continue
            attributes = candidate.get("attributes")
            if isinstance(attributes, dict) and all(key in attributes for key in ("POSITION", "JOINTS_0", "WEIGHTS_0")):
                if primitive is not None:
                    raise SkinQaError("skin QA: multiple skinned primitives are unsupported")
                primitive = candidate
    if primitive is None:
        raise SkinQaError("skin QA: no skinned primitive found")
    attributes = primitive["attributes"]
    positions_raw = _accessor(document, binary, int(attributes["POSITION"]), label="POSITION")
    joints_raw = _accessor(document, binary, int(attributes["JOINTS_0"]), label="JOINTS_0")
    weights_raw = _accessor(document, binary, int(attributes["WEIGHTS_0"]), label="WEIGHTS_0")
    if not (len(positions_raw) == len(joints_raw) == len(weights_raw)):
        raise SkinQaError("skin QA: POSITION/JOINTS_0/WEIGHTS_0 counts differ")
    if any(len(value) != 3 for value in positions_raw) or any(len(value) != 4 for value in joints_raw) or any(len(value) != 4 for value in weights_raw):
        raise SkinQaError("skin QA: skinned accessor dimensions are invalid")

    skin = skins[0]
    skin_joints = skin.get("joints") if isinstance(skin, dict) else None
    if not isinstance(skin_joints, list) or len(skin_joints) < 15:
        raise SkinQaError("skin QA: skin joint list is incomplete")
    for node_index in skin_joints:
        if isinstance(node_index, bool) or not isinstance(node_index, int) or not 0 <= node_index < len(nodes):
            raise SkinQaError("skin QA: skin joint node index is invalid")

    world = _world_matrices(nodes)
    parent_map = _parents(nodes)
    joint_positions: list[tuple[float, float, float]] = []
    joint_regions: list[str] = []
    node_to_skin_index = {node_index: skin_index for skin_index, node_index in enumerate(skin_joints)}
    for node_index in skin_joints:
        matrix = world[node_index]
        joint_positions.append((matrix[0][3], matrix[1][3], matrix[2][3]))
        node = nodes[node_index]
        name = node.get("name") if isinstance(node, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise SkinQaError("skin QA: skin joint is missing a name")
        joint_regions.append(_region(name))

    segments: dict[str, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {
        "torso": [], "left_arm": [], "right_arm": [], "left_leg": [], "right_leg": []
    }
    for skin_index, node_index in enumerate(skin_joints):
        parent_node = parent_map.get(node_index)
        if parent_node in node_to_skin_index:
            parent_skin_index = node_to_skin_index[parent_node]
            segments[joint_regions[skin_index]].append((joint_positions[parent_skin_index], joint_positions[skin_index]))
    for region_name, region_segments in segments.items():
        if not region_segments:
            points = [joint_positions[index] for index, value in enumerate(joint_regions) if value == region_name]
            region_segments.extend((point, point) for point in points)
    if any(not segments[region_name] for region_name in ("left_arm", "right_arm", "left_leg", "right_leg")):
        raise SkinQaError("skin QA: skeleton does not expose all limb regions")

    xs = [point[0] for point in joint_positions]
    ys = [point[1] for point in joint_positions]
    zs = [point[2] for point in joint_positions]
    body_scale = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    if not math.isfinite(body_scale) or body_scale <= 1e-6:
        raise SkinQaError("skin QA: skeleton scale is invalid")

    weight_sum_error_max = 0.0
    zero_weight_vertices = 0
    invalid_joint_indices = 0
    for joint_values, weight_values in zip(joints_raw, weights_raw):
        weights = [float(value) for value in weight_values]
        if not all(math.isfinite(value) and value >= 0.0 for value in weights):
            raise SkinQaError("skin QA: skin weights contain negative/non-finite values")
        total = sum(weights)
        weight_sum_error_max = max(weight_sum_error_max, abs(total - 1.0))
        if total <= 1e-8:
            zero_weight_vertices += 1
        for joint, weight in zip(joint_values, weights):
            if weight > 0.0 and (isinstance(joint, bool) or int(joint) != joint or not 0 <= int(joint) < len(skin_joints)):
                invalid_joint_indices += 1
    if zero_weight_vertices or invalid_joint_indices or weight_sum_error_max > 1e-3:
        raise SkinQaError(
            f"skin QA: invalid skin structure (zero={zero_weight_vertices}, invalid_joint={invalid_joint_indices}, sum_error={weight_sum_error_max:.6g})"
        )

    vertex_count = len(positions_raw)
    stride = max(1, math.ceil(vertex_count / MAX_ANALYZED_VERTICES))
    analyzed_indices = range(0, vertex_count, stride)
    forbidden_weights: list[float] = []
    suspicious = 0
    severe = 0
    classified = 0
    region_stats = {
        name: {"classified": 0, "suspicious": 0, "severe": 0}
        for name in ("left_arm", "right_arm", "left_leg", "right_leg")
    }

    for vertex_index in analyzed_indices:
        raw_position = positions_raw[vertex_index]
        point = (float(raw_position[0]), float(raw_position[1]), float(raw_position[2]))
        if not all(math.isfinite(value) for value in point):
            raise SkinQaError("skin QA: POSITION contains non-finite value")
        distances = {
            region_name: min(_point_segment_distance(point, a, b) for a, b in region_segments)
            for region_name, region_segments in segments.items()
            if region_segments
        }
        ordered = sorted(distances.items(), key=lambda item: item[1])
        nearest_region, nearest_distance = ordered[0]
        second_distance = ordered[1][1]
        if nearest_region == "torso":
            continue
        strong = (
            second_distance >= nearest_distance * STRONG_REGION_MARGIN_RATIO
            or second_distance - nearest_distance >= body_scale * STRONG_REGION_MARGIN_SCALE
        )
        if not strong:
            continue

        classified += 1
        region_stats[nearest_region]["classified"] += 1
        by_region = {name: 0.0 for name in segments}
        for raw_joint, raw_weight in zip(joints_raw[vertex_index], weights_raw[vertex_index]):
            weight = float(raw_weight)
            if weight <= 0:
                continue
            by_region[joint_regions[int(raw_joint)]] += weight
        forbidden_weight = sum(by_region[name] for name in _forbidden(nearest_region))
        forbidden_weights.append(forbidden_weight)
        if forbidden_weight > SUSPICIOUS_WEIGHT:
            suspicious += 1
            region_stats[nearest_region]["suspicious"] += 1
        if forbidden_weight > SEVERE_WEIGHT:
            severe += 1
            region_stats[nearest_region]["severe"] += 1

    if classified == 0:
        raise SkinQaError("skin QA: no strongly classifiable limb vertices found")

    suspicious_ratio = suspicious / classified
    severe_ratio = severe / classified
    mean_forbidden = sum(forbidden_weights) / len(forbidden_weights)
    p95_forbidden = _quantile(forbidden_weights, 0.95)
    max_forbidden = max(forbidden_weights)
    if severe_ratio > 0.002 or p95_forbidden > 0.15 or max_forbidden > 0.75:
        assessment = "high-risk"
    elif suspicious_ratio > 0.01 or p95_forbidden > 0.05:
        assessment = "review"
    else:
        assessment = "low-risk"

    for values in region_stats.values():
        count = values["classified"]
        values["suspicious_ratio"] = round(values["suspicious"] / count, 6) if count else 0.0
        values["severe_ratio"] = round(values["severe"] / count, 6) if count else 0.0

    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": created_at or _utc_now(),
        "package_sha256": package_sha256,
        "avatar_sha256": _sha256_bytes(avatar),
        "body_id": body_id,
        "fitter": {"adapter": "sith-smplx-vrm", "revision": "1"},
        "rig_transfer": {
            "method": "nearest-smplx-vertex-lbs-inverse",
            "nearest_distance_p95": round(float(nearest_p95), 6),
            "nearest_distance_max": round(float(nearest_max), 6),
        },
        "mesh": {
            "vertex_count": vertex_count,
            "joint_count": len(skin_joints),
            "sample_stride": stride,
            "analyzed_vertex_count": math.ceil(vertex_count / stride),
            "limb_classified_vertex_count": classified,
        },
        "weights": {
            "sum_error_max": round(weight_sum_error_max, 9),
            "zero_weight_vertices": zero_weight_vertices,
            "invalid_joint_indices": invalid_joint_indices,
        },
        "cross_region": {
            "suspicious_vertices": suspicious,
            "severe_vertices": severe,
            "suspicious_ratio": round(suspicious_ratio, 6),
            "severe_ratio": round(severe_ratio, 6),
            "forbidden_weight_mean": round(mean_forbidden, 6),
            "forbidden_weight_p95": round(p95_forbidden, 6),
            "forbidden_weight_max": round(max_forbidden, 6),
            "regions": region_stats,
        },
        "thresholds": {
            "suspicious_weight": SUSPICIOUS_WEIGHT,
            "severe_weight": SEVERE_WEIGHT,
            "high_risk_severe_ratio": 0.002,
            "high_risk_p95": 0.15,
            "review_suspicious_ratio": 0.01,
            "review_p95": 0.05,
        },
        "automated_assessment": assessment,
        "structural_pass": True,
        "manual_review_required": True,
    }


def analyze_package(path: str | Path, *, created_at: str | None = None) -> dict[str, Any]:
    package_path = Path(path).expanduser().resolve()
    validated = validate_package(package_path)
    body_id = validated.manifest.get("id")
    if not isinstance(body_id, str) or not body_id:
        raise SkinQaError("skin QA: package body id is invalid")
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SkinQaError("skin QA: package avatar.vrm is unavailable") from exc
    return analyze_vrm_skin(
        avatar,
        package_sha256=_sha256_path(package_path),
        body_id=body_id,
        created_at=created_at,
    )


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise SkinQaError(f"skin QA: report already exists: {destination}") from exc
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze BodyRig high-fidelity skin weights for cross-region leakage risk.")
    parser.add_argument("package", help="Validated high-fidelity .mrbody package")
    parser.add_argument("--out", required=True, help="Create-only bodyrig-skin-qa v1 JSON report")
    args = parser.parse_args(argv)
    try:
        report = analyze_package(args.package)
        output = write_report(args.out, report)
    except (SkinQaError, OSError, ValueError) as exc:
        print(f"BodyRig skin QA: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"report": str(output), "assessment": report["automated_assessment"]}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
