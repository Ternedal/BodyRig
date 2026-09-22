from __future__ import annotations

import hashlib
import json
import struct
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .photoidentity_dental_reconstruction import (
    DENTAL_IMAGE,
    DENTAL_MATERIAL,
    MESH_NAME as SOURCE_MESH_NAME,
    MOUTH_MATERIAL,
    PhotoIdentityDentalReconstructionError,
    _tight_accessor_bytes,
    validate_dental_vrm,
)

FACE_NODE_NAME = "BodyRigFaceSecondaryReview"
FACE_MESH_NAME = "BodyRigFaceSecondaryReviewMesh"
FACE_MOUTH_MATERIAL = "BodyRigMouthInteriorReview"
FACE_TEETH_MATERIAL = "BodyRigTeethReview"
FACE_LASH_MATERIAL = "BodyRigEyelashesReview"
REQUIRED_DENTAL_ROLES = ("mouth_interior", "upper_teeth", "lower_teeth")
REQUIRED_LASH_ROLES = ("left_eyelashes", "right_eyelashes")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class SourceDentalFaceGraftError(RuntimeError):
    pass


def _array(document: dict[str, Any], name: str, *, create: bool = False) -> list[Any]:
    value = document.get(name)
    if value is None and create:
        value = []
        document[name] = value
    if not isinstance(value, list):
        raise SourceDentalFaceGraftError(f"face dental graft requires glTF {name} array")
    return value


def _source_view_bytes(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
) -> bytes:
    views = document.get("bufferViews")
    if not isinstance(views, list):
        raise SourceDentalFaceGraftError(f"{label} requires source bufferViews")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(views)
        or not isinstance(views[index], Mapping)
    ):
        raise SourceDentalFaceGraftError(f"{label} bufferView is invalid")
    view = views[index]
    if view.get("buffer", 0) != 0:
        raise SourceDentalFaceGraftError(f"{label} must use embedded buffer 0")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length < 1
        or offset + length > len(binary)
    ):
        raise SourceDentalFaceGraftError(f"{label} bufferView bounds are invalid")
    return binary[offset : offset + length]


def _source_material(
    source: Mapping[str, Any],
    index: int,
    *,
    expected_name: str,
) -> dict[str, Any]:
    materials = source.get("materials")
    if (
        not isinstance(materials, list)
        or not 0 <= index < len(materials)
        or not isinstance(materials[index], Mapping)
    ):
        raise SourceDentalFaceGraftError(f"source material {expected_name} is missing")
    material = materials[index]
    if material.get("name") != expected_name:
        raise SourceDentalFaceGraftError(f"source material name mismatch: {expected_name}")
    for forbidden in ("normalTexture", "occlusionTexture", "emissiveTexture"):
        if forbidden in material:
            raise SourceDentalFaceGraftError(
                f"source dental material uses unsupported secondary texture: {forbidden}"
            )
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, Mapping) or "baseColorTexture" not in pbr:
        raise SourceDentalFaceGraftError(
            f"source dental material lacks source-derived base color: {expected_name}"
        )
    if "metallicRoughnessTexture" in pbr:
        raise SourceDentalFaceGraftError(
            "source dental material uses unsupported metallic/roughness texture"
        )
    return json.loads(json.dumps(material))


def _canonical_material(source: Mapping[str, Any], *, name: str, texture_index: int) -> dict[str, Any]:
    pbr_source = source.get("pbrMetallicRoughness")
    if not isinstance(pbr_source, Mapping):
        raise SourceDentalFaceGraftError("source dental material PBR block is invalid")
    pbr: dict[str, Any] = {"baseColorTexture": {"index": texture_index}}
    for field in ("baseColorFactor", "metallicFactor", "roughnessFactor"):
        if field in pbr_source:
            pbr[field] = json.loads(json.dumps(pbr_source[field]))
    value: dict[str, Any] = {"name": name, "pbrMetallicRoughness": pbr}
    if source.get("doubleSided") is True:
        value["doubleSided"] = True
    if isinstance(source.get("alphaMode"), str):
        value["alphaMode"] = source["alphaMode"]
    return value


def graft_source_dental_with_lashes(
    destination_vrm: bytes,
    dental_vrm: bytes,
    *,
    head_joint: int,
    jaw_joint: int,
    lash_primitives: list[
        tuple[
            str,
            list[tuple[float, float, float]],
            list[tuple[float, float, float]],
            list[tuple[int, int, int]],
            int,
        ]
    ],
) -> tuple[bytes, dict[str, Any]]:
    try:
        destination, destination_binary_raw = _read_glb(destination_vrm)
        source, source_binary = _read_glb(dental_vrm)
        detail = validate_dental_vrm(dental_vrm)
    except (PbrMaterialError, PhotoIdentityDentalReconstructionError) as exc:
        raise SourceDentalFaceGraftError(str(exc)) from exc

    if {item[0] for item in lash_primitives} != set(REQUIRED_LASH_ROLES):
        raise SourceDentalFaceGraftError("face dental graft requires exactly left/right eyelash geometry")
    if any(item[4] != head_joint for item in lash_primitives):
        raise SourceDentalFaceGraftError("eyelash geometry must bind to canonical destination head joint")

    views = _array(destination, "bufferViews")
    accessors = _array(destination, "accessors")
    materials = _array(destination, "materials")
    meshes = _array(destination, "meshes")
    nodes = _array(destination, "nodes")
    scenes = _array(destination, "scenes")
    buffers = _array(destination, "buffers")
    images = _array(destination, "images", create=True)
    textures = _array(destination, "textures", create=True)
    if len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise SourceDentalFaceGraftError("destination GLB buffer contract is invalid")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise SourceDentalFaceGraftError("destination scene 0 is invalid")

    blocked_material_names = {FACE_MOUTH_MATERIAL, FACE_TEETH_MATERIAL, FACE_LASH_MATERIAL}
    if any(
        isinstance(item, Mapping) and item.get("name") in blocked_material_names
        for item in materials
    ):
        raise SourceDentalFaceGraftError("destination already contains face-secondary review materials")
    if any(isinstance(item, Mapping) and item.get("name") == FACE_NODE_NAME for item in nodes):
        raise SourceDentalFaceGraftError("destination already contains face-secondary review node")
    if any(isinstance(item, Mapping) and item.get("name") == DENTAL_IMAGE for item in images):
        raise SourceDentalFaceGraftError("destination already contains source dental texture")

    source_images = source.get("images")
    if not isinstance(source_images, list) or not 0 <= detail["image_index"] < len(source_images):
        raise SourceDentalFaceGraftError("source dental image is missing")
    source_image = source_images[detail["image_index"]]
    if not isinstance(source_image, Mapping):
        raise SourceDentalFaceGraftError("source dental image is invalid")
    source_texture_bytes = _source_view_bytes(
        source,
        source_binary,
        source_image.get("bufferView"),
        label="source dental image",
    )
    if not source_texture_bytes.startswith(PNG_SIGNATURE):
        raise SourceDentalFaceGraftError("source dental image bytes are not PNG")
    texture_sha = hashlib.sha256(source_texture_bytes).hexdigest()
    if texture_sha != detail["texture_sha256"]:
        raise SourceDentalFaceGraftError("source dental texture changed after candidate validation")

    destination_binary = bytearray(destination_binary_raw)

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(destination_binary) % 4:
            destination_binary.append(0)
        offset = len(destination_binary)
        destination_binary.extend(raw)
        view: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(raw),
        }
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def add_accessor(
        raw: bytes,
        *,
        component: int,
        count: int,
        kind: str,
        target: int,
        source_meta: Mapping[str, Any] | None = None,
    ) -> int:
        value: dict[str, Any] = {
            "bufferView": add_view(raw, target=target),
            "componentType": component,
            "count": count,
            "type": kind,
        }
        if source_meta is not None:
            if source_meta.get("normalized") is True:
                value["normalized"] = True
            for field in ("min", "max"):
                if field in source_meta:
                    value[field] = json.loads(json.dumps(source_meta[field]))
        accessors.append(value)
        return len(accessors) - 1

    image_index = len(images)
    images.append({
        "name": DENTAL_IMAGE,
        "bufferView": add_view(source_texture_bytes),
        "mimeType": "image/png",
    })
    texture_index = len(textures)
    textures.append({"source": image_index})

    mouth_source = _source_material(
        source,
        detail["mouth_material_index"],
        expected_name=MOUTH_MATERIAL,
    )
    dental_source = _source_material(
        source,
        detail["dental_material_index"],
        expected_name=DENTAL_MATERIAL,
    )
    materials.append(_canonical_material(mouth_source, name=FACE_MOUTH_MATERIAL, texture_index=texture_index))
    mouth_material_index = len(materials) - 1
    materials.append(_canonical_material(dental_source, name=FACE_TEETH_MATERIAL, texture_index=texture_index))
    teeth_material_index = len(materials) - 1
    materials.append({
        "name": FACE_LASH_MATERIAL,
        "doubleSided": True,
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.025, 0.018, 0.014, 1.0],
            "metallicFactor": 0.0,
            "roughnessFactor": 0.78,
        },
    })
    lash_material_index = len(materials) - 1

    source_meshes = source.get("meshes")
    if (
        not isinstance(source_meshes, list)
        or not 0 <= detail["mesh_index"] < len(source_meshes)
        or not isinstance(source_meshes[detail["mesh_index"]], Mapping)
    ):
        raise SourceDentalFaceGraftError("source dental mesh is missing")
    source_primitives = source_meshes[detail["mesh_index"]].get("primitives")
    if not isinstance(source_primitives, list):
        raise SourceDentalFaceGraftError("source dental primitives are missing")
    by_role: dict[str, Mapping[str, Any]] = {}
    for primitive in source_primitives:
        if not isinstance(primitive, Mapping):
            raise SourceDentalFaceGraftError("source dental primitive is invalid")
        extras = primitive.get("extras")
        role = extras.get("bodyrigDentalRole") if isinstance(extras, Mapping) else None
        if role in REQUIRED_DENTAL_ROLES:
            by_role[str(role)] = primitive
    if set(by_role) != set(REQUIRED_DENTAL_ROLES):
        raise SourceDentalFaceGraftError("source dental role set is incomplete")

    gltf_primitives: list[dict[str, Any]] = []
    for role in REQUIRED_DENTAL_ROLES:
        primitive = by_role[role]
        attrs = primitive.get("attributes")
        if not isinstance(attrs, Mapping):
            raise SourceDentalFaceGraftError(f"source dental {role} attributes are invalid")

        copied_attrs: dict[str, int] = {}
        vertex_count: int | None = None
        for semantic, component, kind in (
            ("POSITION", 5126, "VEC3"),
            ("NORMAL", 5126, "VEC3"),
            ("TEXCOORD_0", 5126, "VEC2"),
        ):
            try:
                meta, raw = _tight_accessor_bytes(
                    source,
                    source_binary,
                    attrs.get(semantic),
                    label=f"{role} {semantic}",
                    expected_component=component,
                    expected_kind=kind,
                )
            except PhotoIdentityDentalReconstructionError as exc:
                raise SourceDentalFaceGraftError(str(exc)) from exc
            count = int(meta["count"])
            if vertex_count is None:
                vertex_count = count
            elif count != vertex_count:
                raise SourceDentalFaceGraftError(f"source dental {role} attribute counts differ")
            copied_attrs[semantic] = add_accessor(
                raw,
                component=component,
                count=count,
                kind=kind,
                target=34962,
                source_meta=meta,
            )
        assert vertex_count is not None
        destination_joint = head_joint if role == "upper_teeth" else jaw_joint
        copied_attrs["JOINTS_0"] = add_accessor(
            b"".join(struct.pack("<4H", destination_joint, 0, 0, 0) for _ in range(vertex_count)),
            component=5123,
            count=vertex_count,
            kind="VEC4",
            target=34962,
        )
        copied_attrs["WEIGHTS_0"] = add_accessor(
            b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(vertex_count)),
            component=5126,
            count=vertex_count,
            kind="VEC4",
            target=34962,
        )

        source_accessors = source.get("accessors")
        index_index = primitive.get("indices")
        if (
            not isinstance(source_accessors, list)
            or isinstance(index_index, bool)
            or not isinstance(index_index, int)
            or not 0 <= index_index < len(source_accessors)
            or not isinstance(source_accessors[index_index], Mapping)
        ):
            raise SourceDentalFaceGraftError(f"source dental {role} index accessor is invalid")
        index_meta = source_accessors[index_index]
        component = index_meta.get("componentType")
        if component not in {5123, 5125}:
            raise SourceDentalFaceGraftError(f"source dental {role} index component is invalid")
        try:
            copied_index_meta, index_raw = _tight_accessor_bytes(
                source,
                source_binary,
                index_index,
                label=f"{role} indices",
                expected_component=int(component),
                expected_kind="SCALAR",
            )
        except PhotoIdentityDentalReconstructionError as exc:
            raise SourceDentalFaceGraftError(str(exc)) from exc
        index_accessor = add_accessor(
            index_raw,
            component=int(component),
            count=int(copied_index_meta["count"]),
            kind="SCALAR",
            target=34963,
            source_meta=copied_index_meta,
        )
        material = mouth_material_index if role == "mouth_interior" else teeth_material_index
        gltf_primitives.append({
            "attributes": copied_attrs,
            "indices": index_accessor,
            "material": material,
            "mode": 4,
            "extras": {
                "bodyrigFaceSecondaryRole": role,
                "sourceDerivedDentalIdentity": True,
            },
        })

    for role, positions, normals, faces, joint in lash_primitives:
        if not positions or len(positions) != len(normals) or not faces:
            raise SourceDentalFaceGraftError(f"{role} eyelash geometry is empty")
        pos_raw = b"".join(struct.pack("<3f", *item) for item in positions)
        normal_raw = b"".join(struct.pack("<3f", *item) for item in normals)
        joints_raw = b"".join(struct.pack("<4H", joint, 0, 0, 0) for _ in positions)
        weights_raw = b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in positions)
        indices_flat = [index for triangle in faces for index in triangle]
        index_raw = b"".join(struct.pack("<I", index) for index in indices_flat)
        attrs = {
            "POSITION": add_accessor(pos_raw, component=5126, count=len(positions), kind="VEC3", target=34962),
            "NORMAL": add_accessor(normal_raw, component=5126, count=len(normals), kind="VEC3", target=34962),
            "JOINTS_0": add_accessor(joints_raw, component=5123, count=len(positions), kind="VEC4", target=34962),
            "WEIGHTS_0": add_accessor(weights_raw, component=5126, count=len(positions), kind="VEC4", target=34962),
        }
        gltf_primitives.append({
            "attributes": attrs,
            "indices": add_accessor(index_raw, component=5125, count=len(indices_flat), kind="SCALAR", target=34963),
            "material": lash_material_index,
            "mode": 4,
            "extras": {"bodyrigFaceSecondaryRole": role},
        })

    meshes.append({"name": FACE_MESH_NAME, "primitives": gltf_primitives})
    mesh_index = len(meshes) - 1
    nodes.append({"name": FACE_NODE_NAME, "mesh": mesh_index, "skin": 0})
    scenes[0]["nodes"].append(len(nodes) - 1)
    buffers[0]["byteLength"] = len(destination_binary)
    grafted = _write_glb(destination, bytes(destination_binary))
    audit = audit_source_dental_face_payload(grafted, expected_texture_sha256=texture_sha)
    return grafted, audit


def audit_source_dental_face_payload(
    avatar_vrm: bytes,
    *,
    expected_texture_sha256: str,
) -> dict[str, Any]:
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise SourceDentalFaceGraftError(str(exc)) from exc
    meshes = document.get("meshes")
    nodes = document.get("nodes")
    materials = document.get("materials")
    images = document.get("images")
    textures = document.get("textures")
    if not all(isinstance(value, list) for value in (meshes, nodes, materials, images, textures)):
        raise SourceDentalFaceGraftError("grafted face dental payload arrays are incomplete")

    node_matches = [
        item for item in nodes
        if isinstance(item, Mapping) and item.get("name") == FACE_NODE_NAME
    ]
    mesh_matches = [
        (index, item) for index, item in enumerate(meshes)
        if isinstance(item, Mapping) and item.get("name") == FACE_MESH_NAME
    ]
    if len(node_matches) != 1 or len(mesh_matches) != 1:
        raise SourceDentalFaceGraftError("grafted face dental node/mesh is missing or ambiguous")
    mesh_index, mesh = mesh_matches[0]
    node = node_matches[0]
    if node.get("mesh") != mesh_index or node.get("skin") != 0:
        raise SourceDentalFaceGraftError("grafted face dental node does not use mesh/skin 0")

    material_index: dict[str, int] = {}
    for name in (FACE_MOUTH_MATERIAL, FACE_TEETH_MATERIAL, FACE_LASH_MATERIAL):
        matches = [
            index for index, item in enumerate(materials)
            if isinstance(item, Mapping) and item.get("name") == name
        ]
        if len(matches) != 1:
            raise SourceDentalFaceGraftError(f"grafted face material is missing/ambiguous: {name}")
        material_index[name] = matches[0]

    image_matches = [
        (index, item) for index, item in enumerate(images)
        if isinstance(item, Mapping) and item.get("name") == DENTAL_IMAGE
    ]
    if len(image_matches) != 1:
        raise SourceDentalFaceGraftError("grafted source dental image is missing or ambiguous")
    image_index, image = image_matches[0]
    if image.get("mimeType") != "image/png":
        raise SourceDentalFaceGraftError("grafted source dental image is not PNG")
    payload = _source_view_bytes(document, binary, image.get("bufferView"), label="grafted source dental image")
    texture_sha = hashlib.sha256(payload).hexdigest()
    if texture_sha != expected_texture_sha256:
        raise SourceDentalFaceGraftError("grafted source dental texture hash mismatch")

    for name in (FACE_MOUTH_MATERIAL, FACE_TEETH_MATERIAL):
        material = materials[material_index[name]]
        pbr = material.get("pbrMetallicRoughness") if isinstance(material, Mapping) else None
        texture_info = pbr.get("baseColorTexture") if isinstance(pbr, Mapping) else None
        texture_index = texture_info.get("index") if isinstance(texture_info, Mapping) else None
        if (
            isinstance(texture_index, bool)
            or not isinstance(texture_index, int)
            or not 0 <= texture_index < len(textures)
            or not isinstance(textures[texture_index], Mapping)
            or textures[texture_index].get("source") != image_index
        ):
            raise SourceDentalFaceGraftError(f"{name} is not bound to exact source dental texture")

    primitives = mesh.get("primitives")
    if not isinstance(primitives, list):
        raise SourceDentalFaceGraftError("grafted face dental primitives are missing")
    role_material = {
        "mouth_interior": material_index[FACE_MOUTH_MATERIAL],
        "upper_teeth": material_index[FACE_TEETH_MATERIAL],
        "lower_teeth": material_index[FACE_TEETH_MATERIAL],
        "left_eyelashes": material_index[FACE_LASH_MATERIAL],
        "right_eyelashes": material_index[FACE_LASH_MATERIAL],
    }
    seen: set[str] = set()
    for primitive in primitives:
        if not isinstance(primitive, Mapping):
            raise SourceDentalFaceGraftError("grafted face primitive is invalid")
        extras = primitive.get("extras")
        role = extras.get("bodyrigFaceSecondaryRole") if isinstance(extras, Mapping) else None
        if role not in role_material or role in seen:
            raise SourceDentalFaceGraftError("grafted face primitive role is missing/duplicated")
        if primitive.get("material") != role_material[str(role)]:
            raise SourceDentalFaceGraftError(f"grafted face role material mismatch: {role}")
        attrs = primitive.get("attributes")
        if not isinstance(attrs, Mapping) or "POSITION" not in attrs or "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
            raise SourceDentalFaceGraftError(f"grafted face role lacks skinned geometry: {role}")
        if role in REQUIRED_DENTAL_ROLES and extras.get("sourceDerivedDentalIdentity") is not True:
            raise SourceDentalFaceGraftError(f"grafted dental role lost source-derived authority: {role}")
        seen.add(str(role))
    if seen != set(role_material):
        raise SourceDentalFaceGraftError("grafted face role set is incomplete")
    return {
        "texture_sha256": texture_sha,
        "roles": sorted(seen),
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
    }
