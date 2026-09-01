from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from .package import validate_package

FORMAT = "bodyrig-fidelity-ab-evidence"
VERSION = 1
_COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
_INDEX_FORMAT = {5121: "<B", 5123: "<H", 5125: "<I"}


class FidelityAbError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json_sha(value: Any) -> str:
    return _sha256(_json_bytes(value))


def _read_package(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    validated = validate_package(resolved)
    try:
        package_bytes = resolved.read_bytes()
        with zipfile.ZipFile(resolved, "r") as archive:
            avatar = archive.read("avatar.vrm")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            bodyprint = json.loads(archive.read("bodyprint.json").decode("utf-8"))
            provenance = json.loads(archive.read("provenance.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityAbError(f"could not read validated package: {resolved.name}") from exc
    return {
        "path": resolved,
        "package_sha256": _sha256(package_bytes),
        "avatar": avatar,
        "avatar_sha256": _sha256(avatar),
        "manifest": manifest,
        "bodyprint": bodyprint,
        "bodyprint_sha256": _json_sha(bodyprint),
        "provenance": provenance,
        "validated": validated,
    }


def _parse_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise FidelityAbError("avatar is not a GLB v2 container")
    if int.from_bytes(data[4:8], "little") != 2 or int.from_bytes(data[8:12], "little") != len(data):
        raise FidelityAbError("avatar GLB header is invalid")
    offset = 12
    document: dict[str, Any] | None = None
    binary: bytes | None = None
    while offset < len(data):
        if offset + 8 > len(data):
            raise FidelityAbError("avatar GLB chunk header is truncated")
        chunk_length = int.from_bytes(data[offset : offset + 4], "little")
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        end = offset + chunk_length
        if end > len(data):
            raise FidelityAbError("avatar GLB chunk is truncated")
        chunk = data[offset:end]
        offset = end
        if chunk_type == b"JSON":
            if document is not None:
                raise FidelityAbError("avatar GLB has multiple JSON chunks")
            try:
                parsed = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FidelityAbError("avatar GLB JSON is invalid") from exc
            if not isinstance(parsed, dict):
                raise FidelityAbError("avatar GLB JSON must be an object")
            document = parsed
        elif chunk_type == b"BIN\x00":
            if binary is not None:
                raise FidelityAbError("avatar GLB has multiple BIN chunks")
            binary = chunk
    if document is None:
        raise FidelityAbError("avatar GLB JSON chunk is missing")
    if binary is None:
        binary = b""
    buffers = document.get("buffers")
    if not isinstance(buffers, list) or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise FidelityAbError("A/B evidence requires one embedded GLB buffer")
    if "uri" in buffers[0]:
        raise FidelityAbError("A/B evidence refuses external GLB buffers")
    declared = buffers[0].get("byteLength")
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0 or declared > len(binary):
        raise FidelityAbError("GLB buffer byteLength is invalid")
    return document, binary[:declared]


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name, [])
    if not isinstance(value, list):
        raise FidelityAbError(f"glTF {name} must be an array")
    return value


def _accessor_rows(document: Mapping[str, Any], binary: bytes, index: Any) -> tuple[dict[str, Any], list[bytes]]:
    if isinstance(index, bool) or not isinstance(index, int):
        raise FidelityAbError("glTF accessor index is invalid")
    accessors = _array(document, "accessors")
    if not 0 <= index < len(accessors) or not isinstance(accessors[index], dict):
        raise FidelityAbError("glTF accessor is missing")
    accessor = accessors[index]
    if "sparse" in accessor:
        raise FidelityAbError("sparse glTF accessors are not supported by strict A/B evidence")
    view_index = accessor.get("bufferView")
    if isinstance(view_index, bool) or not isinstance(view_index, int):
        raise FidelityAbError("glTF accessor must use an embedded bufferView")
    views = _array(document, "bufferViews")
    if not 0 <= view_index < len(views) or not isinstance(views[view_index], dict):
        raise FidelityAbError("glTF accessor bufferView is missing")
    view = views[view_index]
    if view.get("buffer", 0) != 0:
        raise FidelityAbError("glTF accessor references a non-embedded buffer")
    component_type = accessor.get("componentType")
    accessor_type = accessor.get("type")
    count = accessor.get("count")
    if component_type not in _COMPONENT_SIZE or accessor_type not in _TYPE_COMPONENTS:
        raise FidelityAbError("glTF accessor component/type is unsupported")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FidelityAbError("glTF accessor count is invalid")
    component_size = _COMPONENT_SIZE[component_type]
    components = _TYPE_COMPONENTS[accessor_type]
    if accessor_type.startswith("MAT") and component_size < 4:
        raise FidelityAbError("packed sub-32-bit matrix accessors are not supported")
    element_size = component_size * components
    stride = view.get("byteStride", element_size)
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < element_size:
        raise FidelityAbError("glTF accessor stride is invalid")
    view_offset = view.get("byteOffset", 0)
    accessor_offset = accessor.get("byteOffset", 0)
    view_length = view.get("byteLength")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (view_offset, accessor_offset, view_length)):
        raise FidelityAbError("glTF accessor offsets are invalid")
    start = view_offset + accessor_offset
    rows: list[bytes] = []
    for item in range(count):
        row_start = start + item * stride
        row_end = row_start + element_size
        if row_end > view_offset + view_length or row_end > len(binary):
            raise FidelityAbError("glTF accessor exceeds its bufferView")
        rows.append(binary[row_start:row_end])
    descriptor = {
        "componentType": component_type,
        "type": accessor_type,
        "normalized": bool(accessor.get("normalized", False)),
    }
    return descriptor, rows


def _indices(document: Mapping[str, Any], binary: bytes, primitive: Mapping[str, Any], vertex_count: int) -> list[int]:
    index_accessor = primitive.get("indices")
    if index_accessor is None:
        return list(range(vertex_count))
    descriptor, rows = _accessor_rows(document, binary, index_accessor)
    if descriptor["type"] != "SCALAR" or descriptor["componentType"] not in _INDEX_FORMAT:
        raise FidelityAbError("triangle indices must use an unsigned scalar accessor")
    fmt = _INDEX_FORMAT[descriptor["componentType"]]
    result = [int(struct.unpack(fmt, row)[0]) for row in rows]
    if any(value < 0 or value >= vertex_count for value in result):
        raise FidelityAbError("triangle index exceeds POSITION accessor")
    return result


def _row_signature(label: str, descriptor: Mapping[str, Any], row: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(label.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_json_bytes(dict(descriptor)))
    digest.update(b"\x00")
    digest.update(row)
    return digest.digest()


def _vertex_signature(parts: Iterable[tuple[str, Mapping[str, Any], bytes]]) -> bytes:
    digest = hashlib.sha256()
    for label, descriptor, row in sorted(parts, key=lambda item: item[0]):
        digest.update(_row_signature(label, descriptor, row))
    return digest.digest()


def _canonical_triangle(a: bytes, b: bytes, c: bytes) -> bytes:
    rotations = (a + b + c, b + c + a, c + a + b)
    return min(rotations)


def _digest_records(records: list[bytes], *, label: str) -> str:
    digest = hashlib.sha256()
    digest.update(label.encode("ascii"))
    digest.update(b"\x00")
    for record in sorted(records):
        digest.update(record)
    return digest.hexdigest()


def _mesh_fingerprints(document: Mapping[str, Any], binary: bytes) -> dict[str, Any]:
    geometry_records: list[bytes] = []
    skinned_records: list[bytes] = []
    appearance_records: list[bytes] = []
    triangle_count = 0
    meshes = _array(document, "meshes")
    if not meshes:
        raise FidelityAbError("avatar has no glTF meshes")

    for mesh in meshes:
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives"), list) or not mesh["primitives"]:
            raise FidelityAbError("glTF mesh primitives are invalid")
        for primitive in mesh["primitives"]:
            if not isinstance(primitive, dict) or primitive.get("mode", 4) != 4:
                raise FidelityAbError("A/B evidence requires triangle primitives")
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise FidelityAbError("triangle primitive is missing POSITION")

            attr_rows: dict[str, tuple[dict[str, Any], list[bytes]]] = {}
            for semantic, accessor_index in attributes.items():
                if not isinstance(semantic, str):
                    raise FidelityAbError("glTF attribute semantic is invalid")
                attr_rows[semantic] = _accessor_rows(document, binary, accessor_index)
            position_descriptor, positions = attr_rows["POSITION"]
            vertex_count = len(positions)
            if vertex_count < 3:
                raise FidelityAbError("triangle primitive has too few vertices")
            for semantic, (_, rows) in attr_rows.items():
                if len(rows) != vertex_count:
                    raise FidelityAbError(f"attribute {semantic} count differs from POSITION")

            joint_semantics = sorted(key for key in attr_rows if key.startswith("JOINTS_"))
            weight_semantics = sorted(key for key in attr_rows if key.startswith("WEIGHTS_"))
            if not joint_semantics or joint_semantics != [key.replace("WEIGHTS_", "JOINTS_") for key in weight_semantics]:
                raise FidelityAbError("triangle primitive must have matching JOINTS_n/WEIGHTS_n attributes")

            morph_rows: dict[str, tuple[dict[str, Any], list[bytes]]] = {}
            targets = primitive.get("targets", [])
            if not isinstance(targets, list):
                raise FidelityAbError("glTF morph targets are invalid")
            for target_index, target in enumerate(targets):
                if not isinstance(target, dict):
                    raise FidelityAbError("glTF morph target is invalid")
                for semantic, accessor_index in sorted(target.items()):
                    if semantic not in {"POSITION", "NORMAL", "TANGENT"}:
                        raise FidelityAbError("unsupported morph target semantic in A/B evidence")
                    descriptor, rows = _accessor_rows(document, binary, accessor_index)
                    if len(rows) != vertex_count:
                        raise FidelityAbError("morph target count differs from POSITION")
                    morph_rows[f"MORPH{target_index}:{semantic}"] = (descriptor, rows)

            indices = _indices(document, binary, primitive, vertex_count)
            if len(indices) % 3:
                raise FidelityAbError("triangle index count is not divisible by three")

            material = primitive.get("material")
            materials = _array(document, "materials")
            if material is None:
                material_sha = _sha256(b"null-material")
            else:
                if isinstance(material, bool) or not isinstance(material, int) or not 0 <= material < len(materials):
                    raise FidelityAbError("primitive material index is invalid")
                material_sha = _json_sha(materials[material])
            material_marker = bytes.fromhex(material_sha)

            for offset in range(0, len(indices), 3):
                corners = indices[offset : offset + 3]
                geometry_vertices: list[bytes] = []
                skinned_vertices: list[bytes] = []
                appearance_vertices: list[bytes] = []
                for vertex in corners:
                    geometry_parts: list[tuple[str, Mapping[str, Any], bytes]] = [
                        ("POSITION", position_descriptor, positions[vertex])
                    ]
                    if "NORMAL" in attr_rows:
                        descriptor, rows = attr_rows["NORMAL"]
                        geometry_parts.append(("NORMAL", descriptor, rows[vertex]))
                    for label, (descriptor, rows) in morph_rows.items():
                        geometry_parts.append((label, descriptor, rows[vertex]))
                    geometry_sig = _vertex_signature(geometry_parts)
                    geometry_vertices.append(geometry_sig)

                    skin_parts = list(geometry_parts)
                    for semantic in joint_semantics + weight_semantics:
                        descriptor, rows = attr_rows[semantic]
                        skin_parts.append((semantic, descriptor, rows[vertex]))
                    skinned_vertices.append(_vertex_signature(skin_parts))

                    appearance_parts = list(geometry_parts)
                    for semantic in sorted(
                        key for key in attr_rows if key.startswith("TEXCOORD_") or key.startswith("COLOR_") or key == "TANGENT"
                    ):
                        descriptor, rows = attr_rows[semantic]
                        appearance_parts.append((semantic, descriptor, rows[vertex]))
                    appearance_sig = _vertex_signature(appearance_parts + [("MATERIAL", {"componentType": 5121, "type": "SCALAR", "normalized": False}, material_marker)])
                    appearance_vertices.append(appearance_sig)

                geometry_records.append(_canonical_triangle(*geometry_vertices))
                skinned_records.append(_canonical_triangle(*skinned_vertices))
                appearance_records.append(_canonical_triangle(*appearance_vertices))
                triangle_count += 1

    return {
        "triangle_count": triangle_count,
        "geometry_surface_sha256": _digest_records(geometry_records, label="geometry-surface-v1"),
        "skinned_surface_sha256": _digest_records(skinned_records, label="skinned-surface-v1"),
        "uv_material_mapping_sha256": _digest_records(appearance_records, label="uv-material-mapping-v1"),
    }


def _buffer_view_bytes(document: Mapping[str, Any], binary: bytes, index: Any) -> bytes:
    if isinstance(index, bool) or not isinstance(index, int):
        raise FidelityAbError("bufferView index is invalid")
    views = _array(document, "bufferViews")
    if not 0 <= index < len(views) or not isinstance(views[index], dict):
        raise FidelityAbError("bufferView is missing")
    view = views[index]
    if view.get("buffer", 0) != 0:
        raise FidelityAbError("bufferView references a non-embedded buffer")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (offset, length)):
        raise FidelityAbError("bufferView bounds are invalid")
    if offset + length > len(binary):
        raise FidelityAbError("bufferView exceeds GLB buffer")
    return binary[offset : offset + length]


def _appearance_global_sha(document: Mapping[str, Any], binary: bytes) -> str:
    images_summary: list[dict[str, Any]] = []
    for image in _array(document, "images"):
        if not isinstance(image, dict):
            raise FidelityAbError("glTF image is invalid")
        if "bufferView" in image:
            payload = _buffer_view_bytes(document, binary, image["bufferView"])
            images_summary.append({"mimeType": image.get("mimeType"), "sha256": _sha256(payload)})
        elif isinstance(image.get("uri"), str):
            images_summary.append({"uri": image["uri"]})
        else:
            raise FidelityAbError("glTF image has no embedded payload or URI")
    value = {
        "materials": _array(document, "materials"),
        "textures": _array(document, "textures"),
        "samplers": _array(document, "samplers"),
        "images": images_summary,
    }
    return _json_sha(value)


def _rig_sha(document: Mapping[str, Any], binary: bytes) -> str:
    skins_summary: list[dict[str, Any]] = []
    joint_nodes: set[int] = set()
    nodes = _array(document, "nodes")
    for skin in _array(document, "skins"):
        if not isinstance(skin, dict) or not isinstance(skin.get("joints"), list) or not skin["joints"]:
            raise FidelityAbError("glTF skin is invalid")
        joints: list[int] = []
        for joint in skin["joints"]:
            if isinstance(joint, bool) or not isinstance(joint, int) or not 0 <= joint < len(nodes):
                raise FidelityAbError("glTF skin joint index is invalid")
            joints.append(joint)
            joint_nodes.add(joint)
        inverse = skin.get("inverseBindMatrices")
        if inverse is None:
            inverse_sha = _sha256(b"implicit-inverse-bind-matrices")
        else:
            descriptor, rows = _accessor_rows(document, binary, inverse)
            inverse_sha = _digest_records(
                [_row_signature("inverseBindMatrices", descriptor, row) for row in rows],
                label="inverse-bind-matrices-v1",
            )
        skins_summary.append({"joints": joints, "skeleton": skin.get("skeleton"), "inverse_bind_sha256": inverse_sha})

    extensions = document.get("extensions")
    if not isinstance(extensions, dict):
        raise FidelityAbError("VRM extensions are missing")
    vrm = extensions.get("VRMC_vrm")
    if not isinstance(vrm, dict) or not isinstance(vrm.get("humanoid"), dict):
        raise FidelityAbError("VRM humanoid authority is missing")
    human_bones = vrm["humanoid"].get("humanBones")
    if not isinstance(human_bones, dict):
        raise FidelityAbError("VRM humanBones authority is missing")
    for entry in human_bones.values():
        if isinstance(entry, dict) and isinstance(entry.get("node"), int) and not isinstance(entry.get("node"), bool):
            joint_nodes.add(entry["node"])

    node_summary: dict[str, Any] = {}
    for index in sorted(joint_nodes):
        if not 0 <= index < len(nodes) or not isinstance(nodes[index], dict):
            raise FidelityAbError("rig authority references an invalid node")
        node = nodes[index]
        node_summary[str(index)] = {
            key: node[key]
            for key in ("name", "children", "translation", "rotation", "scale", "matrix")
            if key in node
        }
    return _json_sha({"skins": skins_summary, "nodes": node_summary, "humanBones": human_bones})


def _avatar_fingerprints(data: bytes) -> dict[str, Any]:
    document, binary = _parse_glb(data)
    mesh = _mesh_fingerprints(document, binary)
    return {
        **mesh,
        "rig_sha256": _rig_sha(document, binary),
        "appearance_global_sha256": _appearance_global_sha(document, binary),
        "appearance_sha256": _json_sha(
            {
                "uv_material_mapping_sha256": mesh["uv_material_mapping_sha256"],
                "appearance_global_sha256": _appearance_global_sha(document, binary),
            }
        ),
    }


def compare_packages(left: str | Path, right: str | Path) -> dict[str, Any]:
    left_package = _read_package(left)
    right_package = _read_package(right)
    left_avatar = _avatar_fingerprints(left_package["avatar"])
    right_avatar = _avatar_fingerprints(right_package["avatar"])

    body_id_identical = left_package["manifest"].get("id") == right_package["manifest"].get("id")
    bodyprint_identical = left_package["bodyprint_sha256"] == right_package["bodyprint_sha256"]
    geometry_identical = (
        left_avatar["triangle_count"] == right_avatar["triangle_count"]
        and left_avatar["geometry_surface_sha256"] == right_avatar["geometry_surface_sha256"]
    )
    skin_binding_identical = (
        left_avatar["triangle_count"] == right_avatar["triangle_count"]
        and left_avatar["skinned_surface_sha256"] == right_avatar["skinned_surface_sha256"]
    )
    rig_identical = left_avatar["rig_sha256"] == right_avatar["rig_sha256"]
    appearance_identical = left_avatar["appearance_sha256"] == right_avatar["appearance_sha256"]
    clean_appearance_ab = all(
        (body_id_identical, bodyprint_identical, geometry_identical, skin_binding_identical, rig_identical)
    ) and not appearance_identical

    def side(package: Mapping[str, Any], avatar: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "file_name": Path(package["path"]).name,
            "body_id": package["manifest"].get("id"),
            "builder_revision": package["manifest"].get("builder", {}).get("revision"),
            "package_sha256": package["package_sha256"],
            "avatar_sha256": package["avatar_sha256"],
            "bodyprint_sha256": package["bodyprint_sha256"],
            "triangle_count": avatar["triangle_count"],
            "geometry_surface_sha256": avatar["geometry_surface_sha256"],
            "skinned_surface_sha256": avatar["skinned_surface_sha256"],
            "rig_sha256": avatar["rig_sha256"],
            "appearance_sha256": avatar["appearance_sha256"],
        }

    return {
        "format": FORMAT,
        "version": VERSION,
        "left": side(left_package, left_avatar),
        "right": side(right_package, right_avatar),
        "invariants": {
            "body_id_identical": body_id_identical,
            "bodyprint_identical": bodyprint_identical,
            "geometry_identical": geometry_identical,
            "skin_binding_identical": skin_binding_identical,
            "rig_identical": rig_identical,
            "appearance_identical": appearance_identical,
            "appearance_changed": not appearance_identical,
            "clean_appearance_ab": clean_appearance_ab,
        },
        "human_visual_authority_required": True,
        "comparison_only": True,
        "production_activation": False,
    }
