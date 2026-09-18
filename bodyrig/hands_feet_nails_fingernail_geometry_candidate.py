from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .fidelity_ab import FidelityAbError, _indices
from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    _active_basecolor,
    read_detail_candidate,
)
from .hands_feet_nails_detail_texture import (
    HAND_NAIL_JOINTS,
    NAIL_DISTAL_WEIGHT_THRESHOLD,
    _body_uv_inputs,
    _fingernail_masks,
    _region_masks,
)
from .hands_feet_nails_uv_domain_evidence import (
    HandsFeetNailsUvDomainEvidenceError,
    _canonical_mesh,
    validate_uv_domain_evidence,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-hands-feet-nails-fingernail-geometry-candidate"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-fingernail-geometry-candidate-v1"
EMBEDDED_FORMAT = "bodyrig-hands-feet-nails-fingernail-geometry"
NODE_NAME = "BodyRigFingernailPlates"
MESH_NAME = "BodyRigFingernailPlateMesh"
MATERIAL_NAME = "BodyRigFingernailPlateMaterial"
OFFSET_METERS = 0.00065
GEOMETRY_ROOT = "hands-feet-nails-fingernail-geometry-candidates"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HandsFeetNailsFingernailGeometryError(RuntimeError):
    pass


def _is_numeric_v1(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric == 1.0


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsFingernailGeometryError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsFingernailGeometryError(f"{label} must be a JSON object")
    return value


def _package_avatar(path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry source package is invalid") from exc
    return avatar, str(validated.manifest["id"])


def _uv_evidence(
    root: Path,
    *,
    person_id: str,
    body_revision: str,
    capture_id: str,
    expected_sha256: str,
    expected_source_package_sha256: str,
) -> tuple[dict[str, Any], Path]:
    base = root / "hands-feet-nails-uv-domain-evidence" / person_id / body_revision / capture_id
    matches: list[Path] = []
    if base.is_dir():
        for path in sorted(base.glob("*.json")):
            if _sha256_file(path) == expected_sha256:
                matches.append(path)
    if len(matches) != 1:
        raise HandsFeetNailsFingernailGeometryError(
            "HFN fingernail geometry requires exactly one hash-bound UV-domain evidence file"
        )
    try:
        value = validate_uv_domain_evidence(_read_json(matches[0], label="HFN UV-domain evidence"))
    except HandsFeetNailsUvDomainEvidenceError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    if value["package_sha256"] != expected_source_package_sha256:
        raise HandsFeetNailsFingernailGeometryError(
            "HFN UV-domain evidence belongs to different pre-detail package bytes"
        )
    return value, matches[0]


def geometry_paths(
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> tuple[Path, Path]:
    base = (
        Path(root).expanduser().resolve()
        / GEOMETRY_ROOT
        / str(person_id).strip().lower()
        / str(body_revision).strip().lower()
        / str(capture_id).strip().lower()
    )
    candidate = str(candidate_id).strip().lower()
    return base / f"{candidate}.mrbody", base / f"{candidate}.json"


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HandsFeetNailsFingernailGeometryError(f"glTF {name} array is missing")
    return value


def _indexed(document: Mapping[str, Any], array_name: str, index: Any, *, label: str) -> dict[str, Any]:
    array = _array(document, array_name)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(array) or not isinstance(array[index], dict):
        raise HandsFeetNailsFingernailGeometryError(f"{label} index is invalid")
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
        raise HandsFeetNailsFingernailGeometryError(f"{label} accessor type is not canonical")
    count = accessor.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise HandsFeetNailsFingernailGeometryError(f"{label} accessor count is invalid")
    view = _indexed(document, "bufferViews", accessor.get("bufferView"), label=f"{label} bufferView")
    if view.get("buffer", 0) != 0:
        raise HandsFeetNailsFingernailGeometryError(f"{label} must use GLB buffer 0")
    components = {"VEC2": 2, "VEC3": 3, "VEC4": 4}.get(kind)
    formats = {5123: ("H", 2), 5126: ("f", 4)}
    if components is None or component_type not in formats:
        raise HandsFeetNailsFingernailGeometryError(f"{label} accessor encoding is unsupported")
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
            raise HandsFeetNailsFingernailGeometryError(f"{label} {value_label} is invalid")
    start = view_offset + accessor_offset
    view_end = view_offset + view_length
    if view_end > len(binary) or start < view_offset:
        raise HandsFeetNailsFingernailGeometryError(f"{label} accessor exceeds GLB bytes")
    unpacker = struct.Struct("<" + code * components)
    result: list[tuple[float | int, ...]] = []
    for item in range(count):
        begin = start + item * stride
        end = begin + element_size
        if end > view_end:
            raise HandsFeetNailsFingernailGeometryError(f"{label} accessor exceeds its bufferView")
        result.append(tuple(unpacker.unpack(binary[begin:end])))
    return result


def _normalized_normal(value: tuple[float | int, ...]) -> tuple[float, float, float]:
    if len(value) != 3:
        raise HandsFeetNailsFingernailGeometryError("body normal tuple width is invalid")
    x, y, z = (float(value[0]), float(value[1]), float(value[2]))
    length = math.sqrt(x * x + y * y + z * z)
    if not math.isfinite(length) or length < 1.0e-8:
        raise HandsFeetNailsFingernailGeometryError("body normal is degenerate")
    return x / length, y / length, z / length


def _body_geometry_inputs(
    document: Mapping[str, Any],
    binary: bytes,
) -> tuple[
    dict[str, Any],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[tuple[float | int, ...]],
    list[int],
    list[str],
]:
    _mesh_index, skin_index, _primitive_index, primitive, _joint_nodes, joint_names = _canonical_mesh(document)
    if skin_index != 0:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail plates require canonical skin 0")
    attrs = primitive.get("attributes")
    if not isinstance(attrs, Mapping):
        raise HandsFeetNailsFingernailGeometryError("canonical body primitive attributes are missing")
    try:
        positions = _accessor_values(document, binary, attrs["POSITION"], label="body POSITION", component_type=5126, kind="VEC3")
        normals = _accessor_values(document, binary, attrs["NORMAL"], label="body NORMAL", component_type=5126, kind="VEC3")
        uvs = _accessor_values(document, binary, attrs["TEXCOORD_0"], label="body TEXCOORD_0", component_type=5126, kind="VEC2")
        joints = _accessor_values(document, binary, attrs["JOINTS_0"], label="body JOINTS_0", component_type=5123, kind="VEC4")
        weights = _accessor_values(document, binary, attrs["WEIGHTS_0"], label="body WEIGHTS_0", component_type=5126, kind="VEC4")
    except (KeyError, HandsFeetNailsUvDomainEvidenceError) as exc:
        raise HandsFeetNailsFingernailGeometryError("canonical body geometry/skinning accessors are invalid") from exc
    if not (len(positions) == len(normals) == len(uvs) == len(joints) == len(weights)):
        raise HandsFeetNailsFingernailGeometryError("canonical body geometry accessor counts differ")
    try:
        indices = _indices(document, binary, primitive, len(positions))
    except FidelityAbError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    if len(indices) % 3:
        raise HandsFeetNailsFingernailGeometryError("canonical body triangle index count is invalid")
    return primitive, positions, normals, uvs, joints, weights, indices, joint_names


def _pixel(uv: tuple[float | int, ...], *, width: int, height: int) -> tuple[int, int]:
    u, v = float(uv[0]), float(uv[1])
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        raise HandsFeetNailsFingernailGeometryError("fingernail source UV escaped normalized bounds")
    return (
        min(width - 1, max(0, int(round(u * (width - 1))))),
        min(height - 1, max(0, int(round(v * (height - 1))))),
    )


def _triangle_centroid_uv(
    triangle: list[int],
    uvs: list[tuple[float | int, ...]],
) -> tuple[float, float]:
    return (
        sum(float(uvs[index][0]) for index in triangle) / 3.0,
        sum(float(uvs[index][1]) for index in triangle) / 3.0,
    )


def _fingernail_triangle_groups(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, list[list[int]]]:
    region_masks = _region_masks(document, binary, uv_evidence, width=width, height=height)
    nail_masks = _fingernail_masks(
        document,
        binary,
        uv_evidence,
        region_masks,
        width=width,
        height=height,
    )
    uvs, joints, weights, indices, joint_names = _body_uv_inputs(document, binary, uv_evidence)
    result: dict[str, list[list[int]]] = {}
    claimed: set[int] = set()
    for region in ("left_hand", "right_hand"):
        for nail_label, joint_name in HAND_NAIL_JOINTS[region].items():
            if joint_name not in joint_names:
                raise HandsFeetNailsFingernailGeometryError(f"fingernail joint is missing: {joint_name}")
            joint_index = joint_names.index(joint_name)
            distal_triangles: list[tuple[int, list[int], tuple[float, float]]] = []
            for offset in range(0, len(indices), 3):
                triangle = indices[offset:offset + 3]
                if not all(
                    sum(
                        float(weight)
                        for joint, weight in zip(joints[vertex], weights[vertex], strict=True)
                        if int(joint) == joint_index
                    ) >= NAIL_DISTAL_WEIGHT_THRESHOLD
                    for vertex in triangle
                ):
                    continue
                distal_triangles.append((offset // 3, triangle, _triangle_centroid_uv(triangle, uvs)))
            if not distal_triangles:
                raise HandsFeetNailsFingernailGeometryError(f"{region} {nail_label} has no distal body triangles")

            mask = nail_masks[region][nail_label]
            selected: list[tuple[int, list[int], tuple[float, float]]] = []
            for item in distal_triangles:
                x, y = _pixel(item[2], width=width, height=height)
                if mask.getpixel((x, y)):
                    selected.append(item)
            if not selected:
                bbox = mask.getbbox()
                if bbox is None:
                    raise HandsFeetNailsFingernailGeometryError(f"{region} {nail_label} nail mask is empty")
                target_u = ((bbox[0] + bbox[2] - 1) * 0.5) / float(max(1, width - 1))
                target_v = ((bbox[1] + bbox[3] - 1) * 0.5) / float(max(1, height - 1))
                selected = [
                    min(
                        distal_triangles,
                        key=lambda item: (item[2][0] - target_u) ** 2 + (item[2][1] - target_v) ** 2,
                    )
                ]

            label = f"{region}_{nail_label}"
            group: list[list[int]] = []
            for triangle_index, triangle, _centroid in selected:
                if triangle_index in claimed:
                    raise HandsFeetNailsFingernailGeometryError(
                        "fingernail geometry selection overlaps between nail labels"
                    )
                claimed.add(triangle_index)
                group.append(list(triangle))
            if not group:
                raise HandsFeetNailsFingernailGeometryError(f"{label} produced no nail plate triangles")
            result[label] = group
    if len(result) != 10:
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry must resolve exactly ten nail plates")
    return result


def _pack_f32(rows: list[tuple[float, ...]]) -> bytes:
    return b"".join(struct.pack("<" + "f" * len(row), *row) for row in rows)


def _pack_u16(rows: list[tuple[int, ...]]) -> bytes:
    return b"".join(struct.pack("<" + "H" * len(row), *row) for row in rows)


def _pack_u32(values: list[int]) -> bytes:
    return b"".join(struct.pack("<I", value) for value in values)


def _append_geometry(
    document: dict[str, Any],
    binary_bytes: bytes,
    *,
    uv_evidence: Mapping[str, Any],
    width: int,
    height: int,
    source_detail_package_sha256: str,
    uv_evidence_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    for array_name in ("bufferViews", "accessors", "materials", "meshes", "nodes", "scenes", "buffers"):
        _array(document, array_name)
    if any(
        isinstance(item, Mapping) and item.get("name") in {NODE_NAME, MESH_NAME, MATERIAL_NAME}
        for array_name in ("nodes", "meshes", "materials")
        for item in _array(document, array_name)
    ):
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry is already present")
    if len(_array(document, "buffers")) != 1 or not isinstance(_array(document, "buffers")[0], dict):
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry requires one embedded GLB buffer")
    scenes = _array(document, "scenes")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry requires canonical scene 0")

    _primitive, positions, normals, uvs, joints, weights, _indices_all, _joint_names = _body_geometry_inputs(document, binary_bytes)
    groups = _fingernail_triangle_groups(
        document,
        binary_bytes,
        uv_evidence,
        width=width,
        height=height,
    )

    plate_positions: list[tuple[float, float, float]] = []
    plate_normals: list[tuple[float, float, float]] = []
    plate_uvs: list[tuple[float, float]] = []
    plate_joints: list[tuple[int, int, int, int]] = []
    plate_weights: list[tuple[float, float, float, float]] = []
    plate_indices: list[int] = []
    plate_triangle_counts: dict[str, int] = {}
    for label in sorted(groups):
        triangles = groups[label]
        plate_triangle_counts[label] = len(triangles)
        for triangle in triangles:
            for source_index in triangle:
                normal = _normalized_normal(normals[source_index])
                position = positions[source_index]
                if len(position) != 3:
                    raise HandsFeetNailsFingernailGeometryError("body position tuple width is invalid")
                plate_positions.append((
                    float(position[0]) + normal[0] * OFFSET_METERS,
                    float(position[1]) + normal[1] * OFFSET_METERS,
                    float(position[2]) + normal[2] * OFFSET_METERS,
                ))
                plate_normals.append(normal)
                plate_uvs.append((float(uvs[source_index][0]), float(uvs[source_index][1])))
                joint_row = tuple(int(value) for value in joints[source_index])
                weight_row = tuple(float(value) for value in weights[source_index])
                if len(joint_row) != 4 or len(weight_row) != 4:
                    raise HandsFeetNailsFingernailGeometryError("body skinning tuple width is invalid")
                if any(value < 0 or value > 65535 for value in joint_row):
                    raise HandsFeetNailsFingernailGeometryError("body joint index is outside unsigned-short range")
                if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in weight_row):
                    raise HandsFeetNailsFingernailGeometryError("body skin weight is invalid")
                plate_joints.append(joint_row)  # type: ignore[arg-type]
                plate_weights.append(weight_row)  # type: ignore[arg-type]
                plate_indices.append(len(plate_indices))
    if not plate_positions or len(plate_positions) % 3:
        raise HandsFeetNailsFingernailGeometryError("fingernail plate geometry is empty or non-triangular")

    views = _array(document, "bufferViews")
    accessors = _array(document, "accessors")
    materials = _array(document, "materials")
    meshes = _array(document, "meshes")
    nodes = _array(document, "nodes")
    buffers = _array(document, "buffers")
    binary = bytearray(binary_bytes)

    def add_view(raw: bytes, *, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        return len(views) - 1

    def add_accessor(raw: bytes, *, component_type: int, count: int, kind: str, target: int, bounds: list[tuple[float, ...]] | None = None) -> int:
        view_index = add_view(raw, target=target)
        accessor: dict[str, Any] = {
            "bufferView": view_index,
            "componentType": component_type,
            "count": count,
            "type": kind,
        }
        if bounds is not None:
            columns = list(zip(*bounds, strict=True))
            accessor["min"] = [min(column) for column in columns]
            accessor["max"] = [max(column) for column in columns]
        accessors.append(accessor)
        return len(accessors) - 1

    position_accessor = add_accessor(
        _pack_f32(plate_positions), component_type=5126, count=len(plate_positions), kind="VEC3", target=34962, bounds=plate_positions
    )
    normal_accessor = add_accessor(
        _pack_f32(plate_normals), component_type=5126, count=len(plate_normals), kind="VEC3", target=34962
    )
    uv_accessor = add_accessor(
        _pack_f32(plate_uvs), component_type=5126, count=len(plate_uvs), kind="VEC2", target=34962
    )
    joints_accessor = add_accessor(
        _pack_u16(plate_joints), component_type=5123, count=len(plate_joints), kind="VEC4", target=34962
    )
    weights_accessor = add_accessor(
        _pack_f32(plate_weights), component_type=5126, count=len(plate_weights), kind="VEC4", target=34962
    )
    index_accessor = add_accessor(
        _pack_u32(plate_indices), component_type=5125, count=len(plate_indices), kind="SCALAR", target=34963
    )

    materials.append({
        "name": MATERIAL_NAME,
        "doubleSided": False,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.0,
            "roughnessFactor": 0.28,
        },
    })
    material_index = len(materials) - 1
    meshes.append({
        "name": MESH_NAME,
        "primitives": [{
            "attributes": {
                "POSITION": position_accessor,
                "NORMAL": normal_accessor,
                "TEXCOORD_0": uv_accessor,
                "JOINTS_0": joints_accessor,
                "WEIGHTS_0": weights_accessor,
            },
            "indices": index_accessor,
            "material": material_index,
            "mode": 4,
        }],
    })
    mesh_index = len(meshes) - 1
    nodes.append({"name": NODE_NAME, "mesh": mesh_index, "skin": 0})
    node_index = len(nodes) - 1
    scenes[0]["nodes"].append(node_index)

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry requires BodyRig metadata")
    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "sourceDetailPackageSha256": source_detail_package_sha256,
        "uvEvidenceSha256": uv_evidence_sha256,
        "nodeName": NODE_NAME,
        "meshName": MESH_NAME,
        "materialName": MATERIAL_NAME,
        "skinIndex": 0,
        "plateCount": len(plate_triangle_counts),
        "triangleCount": len(plate_indices) // 3,
        "vertexCount": len(plate_positions),
        "plateTriangleCounts": dict(sorted(plate_triangle_counts.items())),
        "offsetMeters": OFFSET_METERS,
        "sourceGrounded": True,
        "additiveGeometryOnly": True,
        "geometryModified": True,
        "textureModified": False,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    bodyrig["handsFeetNailsFingernailGeometry"] = embedded
    buffers[0]["byteLength"] = len(binary)
    try:
        result = _write_glb(document, bytes(binary))
    except PbrMaterialError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    return result, embedded


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [item.filename for item in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsFingernailGeometryError("could not read HFN detail candidate package") from exc
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HandsFeetNailsFingernailGeometryError(f"refusing to overwrite fingernail geometry candidate: {destination}") from exc
    except OSError as exc:
        raise HandsFeetNailsFingernailGeometryError("could not write fingernail geometry candidate") from exc


def build_fingernail_geometry_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    try:
        detail = read_detail_candidate(
            root_path,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
            candidate_id=candidate_id,
        )
    except HandsFeetNailsDetailCandidateError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    source_package = Path(detail["package_path"]).expanduser().resolve()
    source_avatar, body_id = _package_avatar(source_package)
    if body_id != detail["body_id"] or _sha256_file(source_package) != detail["candidate_package_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("HFN detail candidate package identity changed")
    uv, uv_path = _uv_evidence(
        root_path,
        person_id=detail["person_id"],
        body_revision=detail["body_revision"],
        capture_id=detail["capture_id"],
        expected_sha256=detail["uv_evidence_sha256"],
        expected_source_package_sha256=detail["source_package_sha256"],
    )
    try:
        document, binary = _read_glb(source_avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    mesh_index, skin_index, _primitive_index, _primitive, _joint_nodes, _joint_names = _canonical_mesh(document)
    if skin_index != 0:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry requires skin 0")
    base_mesh_before = copy.deepcopy(_array(document, "meshes")[mesh_index])
    base_skin_before = copy.deepcopy(_array(document, "skins")[skin_index])
    basecolor, _image, _views, _bodyrig, _appearance = _active_basecolor(
        document,
        binary,
        reject_existing_application=False,
    )
    try:
        with Image.open(__import__("io").BytesIO(basecolor)) as image:
            width, height = image.size
    except (OSError, ValueError) as exc:
        raise HandsFeetNailsFingernailGeometryError("HFN detail base color is unreadable") from exc
    if width < 64 or height < 64:
        raise HandsFeetNailsFingernailGeometryError("HFN detail base color is too small for nail geometry")

    geometry_avatar, embedded = _append_geometry(
        document,
        binary,
        uv_evidence=uv,
        width=width,
        height=height,
        source_detail_package_sha256=detail["candidate_package_sha256"],
        uv_evidence_sha256=detail["uv_evidence_sha256"],
    )
    try:
        after_document, after_binary = _read_glb(geometry_avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    after_mesh_index, after_skin_index, _p, _prim, _jn, _names = _canonical_mesh(after_document)
    if after_mesh_index != mesh_index or after_skin_index != skin_index:
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry changed canonical body mesh/skin identity")
    if _array(after_document, "meshes")[mesh_index] != base_mesh_before:
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry mutated canonical body mesh")
    if _array(after_document, "skins")[skin_index] != base_skin_before:
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry mutated canonical SMPL-X skin")
    after_basecolor, _i, _v, _b, _a = _active_basecolor(
        after_document,
        after_binary,
        reject_existing_application=False,
    )
    if _sha256_bytes(after_basecolor) != detail["candidate_basecolor_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("fingernail geometry changed HFN detail texture bytes")

    package_out, receipt_out = geometry_paths(
        root_path,
        detail["person_id"],
        detail["body_revision"],
        detail["capture_id"],
        detail["candidate_id"],
    )
    if package_out.exists() or receipt_out.exists():
        raise HandsFeetNailsFingernailGeometryError("refusing to overwrite existing fingernail geometry authority")
    package_created = False
    receipt_created = False
    try:
        _rewrite_package(source_package, package_out, avatar_vrm=geometry_avatar)
        package_created = True
        try:
            validated = validate_package(package_out)
        except MRBodyError as exc:
            raise HandsFeetNailsFingernailGeometryError(f"fingernail geometry package validation failed: {exc}") from exc
        if validated.manifest["id"] != body_id:
            raise HandsFeetNailsFingernailGeometryError("fingernail geometry changed canonical body id")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "candidate_id": detail["candidate_id"],
            "person_id": detail["person_id"],
            "body_revision": detail["body_revision"],
            "capture_id": detail["capture_id"],
            "body_id": body_id,
            "bodyrig_revision": detail["bodyrig_revision"],
            "source_detail_receipt_sha256": _sha256_file(Path(detail["receipt_path"])),
            "source_detail_package_sha256": detail["candidate_package_sha256"],
            "geometry_package_sha256": _sha256_file(package_out),
            "source_avatar_sha256": detail["candidate_avatar_sha256"],
            "geometry_avatar_sha256": _sha256_bytes(geometry_avatar),
            "uv_evidence_sha256": detail["uv_evidence_sha256"],
            "uv_evidence_path_sha256": _sha256_file(uv_path),
            "active_basecolor_sha256": detail["candidate_basecolor_sha256"],
            "node_name": NODE_NAME,
            "mesh_name": MESH_NAME,
            "material_name": MATERIAL_NAME,
            "plate_count": embedded["plateCount"],
            "triangle_count": embedded["triangleCount"],
            "vertex_count": embedded["vertexCount"],
            "plate_triangle_counts": embedded["plateTriangleCounts"],
            "offset_meters": OFFSET_METERS,
            "skin_index": 0,
            "source_grounded": True,
            "additive_geometry_only": True,
            "geometry_modified": True,
            "texture_modified": False,
            "human_review_required": True,
            "production_activation": False,
        }
        receipt_out.parent.mkdir(parents=True, exist_ok=True)
        with receipt_out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
        receipt_created = True
        return {**receipt, "package_path": str(package_out), "receipt_path": str(receipt_out)}
    except Exception:
        if receipt_created:
            receipt_out.unlink(missing_ok=True)
        if package_created:
            package_out.unlink(missing_ok=True)
        raise


def read_fingernail_geometry_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    package_path, receipt_path = geometry_paths(root, person_id, body_revision, capture_id, candidate_id)
    receipt = _read_json(receipt_path, label="HFN fingernail geometry receipt")
    if receipt.get("format") != FORMAT or not _is_numeric_v1(receipt.get("version")) or receipt.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry receipt format/version/policy mismatch")
    for field in (
        "source_detail_receipt_sha256", "source_detail_package_sha256", "geometry_package_sha256",
        "source_avatar_sha256", "geometry_avatar_sha256", "uv_evidence_sha256",
        "uv_evidence_path_sha256", "active_basecolor_sha256",
    ):
        value = str(receipt.get(field) or "").lower()
        if not SHA_RE.fullmatch(value):
            raise HandsFeetNailsFingernailGeometryError(f"HFN fingernail geometry {field} is invalid")
    if (
        receipt.get("node_name") != NODE_NAME
        or receipt.get("mesh_name") != MESH_NAME
        or receipt.get("material_name") != MATERIAL_NAME
        or receipt.get("plate_count") != 10
        or receipt.get("skin_index") != 0
        or receipt.get("offset_meters") != OFFSET_METERS
        or receipt.get("source_grounded") is not True
        or receipt.get("additive_geometry_only") is not True
        or receipt.get("geometry_modified") is not True
        or receipt.get("texture_modified") is not False
        or receipt.get("human_review_required") is not True
        or receipt.get("production_activation") is not False
    ):
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry receipt authority is invalid")
    counts = receipt.get("plate_triangle_counts")
    if not isinstance(counts, Mapping) or len(counts) != 10 or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in counts.values()):
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry plate counts are invalid")
    if sum(int(value) for value in counts.values()) != receipt.get("triangle_count"):
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry triangle accounting is inconsistent")
    if receipt.get("vertex_count") != int(receipt["triangle_count"]) * 3:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry vertex accounting is inconsistent")
    if not package_path.is_file() or _sha256_file(package_path) != receipt["geometry_package_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry package bytes changed")
    avatar, body_id = _package_avatar(package_path)
    if body_id != receipt.get("body_id") or _sha256_bytes(avatar) != receipt["geometry_avatar_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry avatar/body identity changed")
    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsFingernailGeometryError(str(exc)) from exc
    nodes = [item for item in _array(document, "nodes") if isinstance(item, Mapping) and item.get("name") == NODE_NAME]
    meshes = [item for item in _array(document, "meshes") if isinstance(item, Mapping) and item.get("name") == MESH_NAME]
    materials = [item for item in _array(document, "materials") if isinstance(item, Mapping) and item.get("name") == MATERIAL_NAME]
    if len(nodes) != 1 or len(meshes) != 1 or len(materials) != 1:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry render payload is missing or ambiguous")
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    embedded = bodyrig.get("handsFeetNailsFingernailGeometry") if isinstance(bodyrig, Mapping) else None
    if not isinstance(embedded, Mapping) or embedded.get("sourceDetailPackageSha256") != receipt["source_detail_package_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("embedded HFN fingernail geometry authority is stale")
    basecolor, _i, _v, _b, _a = _active_basecolor(document, binary, reject_existing_application=False)
    if _sha256_bytes(basecolor) != receipt["active_basecolor_sha256"]:
        raise HandsFeetNailsFingernailGeometryError("HFN fingernail geometry active base color changed")
    return {**receipt, "package_path": str(package_path), "receipt_path": str(receipt_path)}
