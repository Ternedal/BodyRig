from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import (
    FidelityComponentError,
    validate_receipt,
    with_face_secondary_receipt,
)
from .bridges.face_secondary_fidelity import (
    FaceSecondaryFidelityError,
    validate_face_secondary_receipt,
)
from .package import MRBodyError, validate_package


FORMAT = "bodyrig-high-fidelity-package-audit"
VERSION = 1
GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"

HAIR_NODE = "BodyRigSourceHairReview"
HAIR_MESH = "BodyRigSourceHairReviewMesh"
HAIR_MATERIAL = "BodyRigSourceHairReviewMaterial"
HAIR_IMAGE = "BodyRigSourceHairReviewTexture"

EYE_NODE = "BodyRigSourceEyeReview"
EYE_MESH = "BodyRigSourceEyeReviewMesh"
EYE_SURFACE_MATERIAL = "BodyRigSourceEyeSurface"
EYE_CORNEA_MATERIAL = "BodyRigCorneaReview"
EYE_IMAGE = "BodyRigSourceEyeBake"

FACE_NODE = "BodyRigFaceSecondaryReview"
FACE_MESH = "BodyRigFaceSecondaryReviewMesh"
FACE_MATERIALS = (
    "BodyRigMouthInteriorReview",
    "BodyRigTeethReview",
    "BodyRigEyelashesReview",
)


class HighFidelityPackageAuditError(ValueError):
    pass


def _read_glb_document(value: bytes) -> dict[str, Any]:
    if not isinstance(value, bytes) or len(value) < 20 or value[:4] != GLB_MAGIC:
        raise HighFidelityPackageAuditError("avatar.vrm is not a GLB/VRM")
    version, declared_length = struct.unpack("<II", value[4:12])
    if version != 2 or declared_length != len(value):
        raise HighFidelityPackageAuditError("avatar.vrm GLB header is invalid")
    offset = 12
    document: dict[str, Any] | None = None
    while offset + 8 <= len(value):
        length, kind = struct.unpack("<I4s", value[offset:offset + 8])
        offset += 8
        end = offset + length
        if end > len(value):
            raise HighFidelityPackageAuditError("avatar.vrm GLB chunk is truncated")
        payload = value[offset:end]
        offset = end
        if kind != JSON_CHUNK:
            continue
        if document is not None:
            raise HighFidelityPackageAuditError("avatar.vrm contains multiple JSON chunks")
        try:
            raw = json.loads(
                payload.rstrip(b" \x00").decode("utf-8"),
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HighFidelityPackageAuditError("avatar.vrm GLB JSON is invalid") from exc
        if not isinstance(raw, dict):
            raise HighFidelityPackageAuditError("avatar.vrm GLB JSON document is not an object")
        document = raw
    if document is None:
        raise HighFidelityPackageAuditError("avatar.vrm GLB has no JSON document")
    return document


def _array(document: Mapping[str, Any], name: str, *, label: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HighFidelityPackageAuditError(f"{label} requires glTF {name} array")
    return value


def _named_index(document: Mapping[str, Any], array_name: str, name: str, *, label: str) -> int:
    array = _array(document, array_name, label=label)
    matches = [
        index
        for index, item in enumerate(array)
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise HighFidelityPackageAuditError(
            f"{label} requires exactly one {array_name} entry named {name}; found {len(matches)}"
        )
    return matches[0]


def _indexed(document: Mapping[str, Any], array_name: str, index: Any, *, label: str) -> dict[str, Any]:
    array = _array(document, array_name, label=label)
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        or index >= len(array)
        or not isinstance(array[index], dict)
    ):
        raise HighFidelityPackageAuditError(f"{label} has invalid {array_name} index")
    return array[index]


def _bodyrig(document: Mapping[str, Any]) -> Mapping[str, Any]:
    extras = document.get("extras") if isinstance(document, Mapping) else None
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, Mapping):
        raise HighFidelityPackageAuditError("BodyRig VRM metadata is missing")
    return bodyrig


def _require_promotion(
    bodyrig: Mapping[str, Any],
    field: str,
    *,
    expected_format: str,
    component: str,
) -> Mapping[str, Any]:
    value = bodyrig.get(field)
    if not isinstance(value, Mapping):
        raise HighFidelityPackageAuditError(
            f"{component}=complete without embedded {field} authority"
        )
    if (
        value.get("format") != expected_format
        or value.get("version") != 1
        or value.get("component") != component
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityPackageAuditError(
            f"{component}=complete with invalid embedded {field} authority"
        )
    return value


def _require_scene_mesh(
    document: Mapping[str, Any],
    *,
    component: str,
    node_name: str,
    mesh_name: str,
) -> tuple[int, int, dict[str, Any]]:
    node_index = _named_index(document, "nodes", node_name, label=f"{component} render payload")
    mesh_index = _named_index(document, "meshes", mesh_name, label=f"{component} render payload")
    node = _indexed(document, "nodes", node_index, label=f"{component} render node")
    if node.get("mesh") != mesh_index or node.get("skin") != 0:
        raise HighFidelityPackageAuditError(
            f"{component}=complete but canonical render node is not bound to mesh/skin 0"
        )
    scenes = _array(document, "scenes", label=f"{component} render payload")
    if not scenes or not isinstance(scenes[0], Mapping):
        raise HighFidelityPackageAuditError(f"{component}=complete without canonical scene 0")
    scene_nodes = scenes[0].get("nodes")
    if not isinstance(scene_nodes, list) or node_index not in scene_nodes:
        raise HighFidelityPackageAuditError(
            f"{component}=complete but canonical render node is not active in scene 0"
        )
    mesh = _indexed(document, "meshes", mesh_index, label=f"{component} render mesh")
    primitives = mesh.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        raise HighFidelityPackageAuditError(f"{component}=complete but canonical render mesh is empty")
    return node_index, mesh_index, mesh


def _primitive_materials(mesh: Mapping[str, Any], *, component: str) -> set[int]:
    primitives = mesh.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        raise HighFidelityPackageAuditError(f"{component}=complete but canonical render mesh is empty")
    material_indexes: set[int] = set()
    for primitive in primitives:
        if not isinstance(primitive, Mapping):
            raise HighFidelityPackageAuditError(f"{component} render mesh contains invalid primitive")
        attributes = primitive.get("attributes")
        if not isinstance(attributes, Mapping) or "POSITION" not in attributes:
            raise HighFidelityPackageAuditError(
                f"{component} render primitive has no POSITION attribute"
            )
        material = primitive.get("material")
        if isinstance(material, bool) or not isinstance(material, int) or material < 0:
            raise HighFidelityPackageAuditError(
                f"{component} render primitive has invalid material binding"
            )
        material_indexes.add(material)
    return material_indexes


def _require_material_image_binding(
    document: Mapping[str, Any],
    *,
    component: str,
    material_index: int,
    image_index: int,
) -> None:
    material = _indexed(document, "materials", material_index, label=f"{component} render material")
    pbr = material.get("pbrMetallicRoughness")
    base_color = pbr.get("baseColorTexture") if isinstance(pbr, Mapping) else None
    texture_index = base_color.get("index") if isinstance(base_color, Mapping) else None
    texture = _indexed(document, "textures", texture_index, label=f"{component} base-color texture")
    if texture.get("source") != image_index:
        raise HighFidelityPackageAuditError(
            f"{component}=complete but canonical material is not bound to canonical image"
        )


def _audit_hair_payload(document: Mapping[str, Any], bodyrig: Mapping[str, Any]) -> dict[str, Any]:
    promotion = _require_promotion(
        bodyrig,
        "hairPromotion",
        expected_format="bodyrig-hair-promotion",
        component="hair",
    )
    if promotion.get("eyesImported") is not False:
        raise HighFidelityPackageAuditError("hair promotion unexpectedly claims imported eye runtime")
    node_index, mesh_index, mesh = _require_scene_mesh(
        document,
        component="hair",
        node_name=HAIR_NODE,
        mesh_name=HAIR_MESH,
    )
    material_index = _named_index(
        document, "materials", HAIR_MATERIAL, label="hair render payload"
    )
    image_index = _named_index(document, "images", HAIR_IMAGE, label="hair render payload")
    if material_index not in _primitive_materials(mesh, component="hair"):
        raise HighFidelityPackageAuditError(
            "hair=complete but canonical hair material is not used by the hair mesh"
        )
    _require_material_image_binding(
        document,
        component="hair",
        material_index=material_index,
        image_index=image_index,
    )
    return {
        "node": node_index,
        "mesh": mesh_index,
        "material": material_index,
        "image": image_index,
    }


def _audit_eye_payload(document: Mapping[str, Any], bodyrig: Mapping[str, Any]) -> dict[str, Any]:
    promotion = _require_promotion(
        bodyrig,
        "eyePromotion",
        expected_format="bodyrig-eye-promotion",
        component="eyes",
    )
    if (
        promotion.get("sourceEyeRuntimeImported") is not True
        or promotion.get("sourceHairRuntimeImported") is not False
    ):
        raise HighFidelityPackageAuditError("eyes promotion runtime-import authority is invalid")
    node_index, mesh_index, mesh = _require_scene_mesh(
        document,
        component="eyes",
        node_name=EYE_NODE,
        mesh_name=EYE_MESH,
    )
    surface_index = _named_index(
        document, "materials", EYE_SURFACE_MATERIAL, label="eyes render payload"
    )
    cornea_index = _named_index(
        document, "materials", EYE_CORNEA_MATERIAL, label="eyes render payload"
    )
    image_index = _named_index(document, "images", EYE_IMAGE, label="eyes render payload")
    used = _primitive_materials(mesh, component="eyes")
    if not {surface_index, cornea_index}.issubset(used):
        raise HighFidelityPackageAuditError(
            "eyes=complete but eye surface/cornea materials are not both used by the eye mesh"
        )
    _require_material_image_binding(
        document,
        component="eyes",
        material_index=surface_index,
        image_index=image_index,
    )
    return {
        "node": node_index,
        "mesh": mesh_index,
        "surface_material": surface_index,
        "cornea_material": cornea_index,
        "image": image_index,
    }


def _audit_face_payload(document: Mapping[str, Any], bodyrig: Mapping[str, Any]) -> dict[str, Any]:
    _require_promotion(
        bodyrig,
        "faceSecondaryPromotion",
        expected_format="bodyrig-face-secondary-promotion",
        component="face_secondary",
    )
    node_index, mesh_index, mesh = _require_scene_mesh(
        document,
        component="face_secondary",
        node_name=FACE_NODE,
        mesh_name=FACE_MESH,
    )
    material_indexes = {
        name: _named_index(document, "materials", name, label="face_secondary render payload")
        for name in FACE_MATERIALS
    }
    used = _primitive_materials(mesh, component="face_secondary")
    if not set(material_indexes.values()).issubset(used):
        raise HighFidelityPackageAuditError(
            "face_secondary=complete but canonical secondary-face materials are not all used"
        )
    return {
        "node": node_index,
        "mesh": mesh_index,
        "materials": material_indexes,
    }


def audit_fidelity_document(document: Mapping[str, Any]) -> dict[str, Any]:
    bodyrig = _bodyrig(document)

    top_raw = bodyrig.get("fidelityComponents")
    face_raw = bodyrig.get("faceSecondaryFidelity")
    if not isinstance(top_raw, Mapping):
        raise HighFidelityPackageAuditError("BodyRig fidelityComponents receipt is missing")
    if not isinstance(face_raw, Mapping):
        raise HighFidelityPackageAuditError("BodyRig faceSecondaryFidelity receipt is missing")
    try:
        top = validate_receipt(top_raw)
        face = validate_face_secondary_receipt(face_raw)
        expected_top = with_face_secondary_receipt(
            top,
            face_secondary_receipt=face,
        )
    except (FidelityComponentError, FaceSecondaryFidelityError) as exc:
        raise HighFidelityPackageAuditError(str(exc)) from exc

    if top != expected_top:
        raise HighFidelityPackageAuditError(
            "top-level face_secondary status is inconsistent with nested face-secondary receipt"
        )

    render_payloads: dict[str, Any] = {}
    if top["components"]["hair"] == "complete":
        render_payloads["hair"] = _audit_hair_payload(document, bodyrig)
    if top["components"]["eyes"] == "complete":
        render_payloads["eyes"] = _audit_eye_payload(document, bodyrig)
    if top["components"]["face_secondary"] == "complete":
        render_payloads["face_secondary"] = _audit_face_payload(document, bodyrig)

    return {
        "components": dict(top["components"]),
        "high_fidelity_ready": bool(top["highFidelityReady"]),
        "top_level_blockers": list(top["blockers"]),
        "face_secondary_components": dict(face["components"]),
        "face_secondary_ready": bool(face["faceSecondaryReady"]),
        "face_secondary_blockers": list(face["blockers"]),
        "semantic_vertex_map_authority": str(face["semanticVertexMapAuthority"]),
        "render_payloads": render_payloads,
        "human_review_required": bool(top["humanReviewRequired"] and face["humanReviewRequired"]),
        "production_ready": bool(top["productionReady"] or face["productionReady"]),
    }


def audit_high_fidelity_package(path: str | Path) -> dict[str, Any]:
    package = Path(path).expanduser().resolve()
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise HighFidelityPackageAuditError(str(exc)) from exc
    try:
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise HighFidelityPackageAuditError("could not read validated avatar.vrm") from exc

    fidelity = audit_fidelity_document(_read_glb_document(avatar))
    return {
        "format": FORMAT,
        "version": VERSION,
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "canonical_body_id": validated.manifest["id"],
        **fidelity,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate BodyRig high-fidelity component authority and concrete render payload "
            "inside a strict .mrbody package."
        )
    )
    parser.add_argument("package")
    args = parser.parse_args(argv)
    try:
        result = audit_high_fidelity_package(args.package)
    except (OSError, HighFidelityPackageAuditError) as exc:
        print(f"BodyRig high-fidelity package audit: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
