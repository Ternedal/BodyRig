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
from .fine_identity_application import (
    FineIdentityApplicationError,
    validate_application as validate_fine_identity_application,
    validate_requirement as validate_fine_identity_requirement,
)
from .photoidentity_dental_graft import (
    GRAFT_DENTAL_MATERIAL,
    GRAFT_MESH_NAME,
    GRAFT_MOUTH_MATERIAL,
    GRAFT_NODE_NAME,
)
from .package import MRBodyError, validate_package


FORMAT = "bodyrig-high-fidelity-package-audit"
VERSION = 1
GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"
BIN_CHUNK = b"BIN\x00"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

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

HFN_IMAGE = "BodyRigHandsFeetNailsDetailBaseColor"
HFN_APPLICATION_FORMAT = "bodyrig-hands-feet-nails-detail-application"
HFN_POLICY_REVISION = "bodyrig-hands-feet-nails-detail-candidate-v1"
HFN_REGIONS = frozenset({"left_hand", "right_hand", "left_foot", "right_foot"})
HFN_APPLICATION_FIELDS = {
    "format", "version", "policyRevision", "candidateId", "personId", "bodyRevision",
    "captureId", "bodyrigRevision", "method", "sourcePackageSha256", "sourceCaptureSha256",
    "landmarkEvidenceSha256", "uvEvidenceSha256", "sourceBaseColorSha256",
    "candidateBaseColorSha256", "maxChannelDeltaLevels", "regions", "geometrySurfaceSha256",
    "skinnedSurfaceSha256", "rigSha256", "uvMaterialMappingSha256", "sourceGrounded",
    "generative", "packageApplicationAuthority", "geometryModified", "textureModified",
    "humanReviewRequired", "productionActivation",
}


class HighFidelityPackageAuditError(ValueError):
    pass


def _is_numeric_v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


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


def _read_glb_binary(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 20 or value[:4] != GLB_MAGIC:
        raise HighFidelityPackageAuditError("avatar.vrm is not a GLB/VRM")
    version, declared_length = struct.unpack("<II", value[4:12])
    if version != 2 or declared_length != len(value):
        raise HighFidelityPackageAuditError("avatar.vrm GLB header is invalid")
    offset = 12
    binary: bytes | None = None
    while offset + 8 <= len(value):
        length, kind = struct.unpack("<I4s", value[offset:offset + 8])
        offset += 8
        end = offset + length
        if end > len(value):
            raise HighFidelityPackageAuditError("avatar.vrm GLB chunk is truncated")
        payload = value[offset:end]
        offset = end
        if kind != BIN_CHUNK:
            continue
        if binary is not None:
            raise HighFidelityPackageAuditError("avatar.vrm contains multiple BIN chunks")
        binary = payload
    if binary is None:
        raise HighFidelityPackageAuditError("avatar.vrm GLB has no BIN chunk")
    return binary


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
        or not _is_numeric_v1(value.get("version"))
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


def _buffer_view_bytes(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
) -> bytes:
    view = _indexed(document, "bufferViews", index, label=label)
    if view.get("buffer", 0) != 0:
        raise HighFidelityPackageAuditError(f"{label} must use embedded buffer 0")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length < 0
        or offset + length > len(binary)
    ):
        raise HighFidelityPackageAuditError(f"{label} bufferView bounds are invalid")
    return binary[offset:offset + length]


def _canonical_sha256(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise HighFidelityPackageAuditError(f"{label} is not a canonical SHA-256")
    return text


def _audit_hfn_payload(
    document: Mapping[str, Any],
    binary: bytes,
    bodyrig: Mapping[str, Any],
) -> dict[str, Any] | None:
    application = bodyrig.get("handsFeetNailsDetailApplication")
    if application is None:
        return None
    if not isinstance(application, Mapping) or set(application) != HFN_APPLICATION_FIELDS:
        raise HighFidelityPackageAuditError(
            "HFN detail application metadata fields are not canonical"
        )
    version = application.get("version")
    method = application.get("method")
    regions = application.get("regions")
    if (
        application.get("format") != HFN_APPLICATION_FORMAT
        or isinstance(version, bool)
        or version != 1
        or application.get("policyRevision") != HFN_POLICY_REVISION
        or not isinstance(method, str)
        or not method.strip()
        or not isinstance(regions, Mapping)
        or set(regions) != HFN_REGIONS
    ):
        raise HighFidelityPackageAuditError(
            "HFN detail application format/version/policy/method/regions are invalid"
        )
    for field in ("sourceGrounded", "packageApplicationAuthority", "textureModified", "humanReviewRequired"):
        if application.get(field) is not True:
            raise HighFidelityPackageAuditError(f"HFN detail application {field} authority is invalid")
    for field in ("generative", "geometryModified", "productionActivation"):
        if application.get(field) is not False:
            raise HighFidelityPackageAuditError(f"HFN detail application {field} authority is invalid")

    source_sha = _canonical_sha256(
        application.get("sourceBaseColorSha256"),
        label="HFN source base-color SHA-256",
    )
    candidate_sha = _canonical_sha256(
        application.get("candidateBaseColorSha256"),
        label="HFN candidate base-color SHA-256",
    )
    if source_sha == candidate_sha:
        raise HighFidelityPackageAuditError(
            "HFN detail application does not change active base-color bytes"
        )

    appearance = bodyrig.get("appearanceTransfer")
    if not isinstance(appearance, Mapping):
        raise HighFidelityPackageAuditError(
            "HFN detail application has no active appearanceTransfer authority"
        )
    if _canonical_sha256(
        appearance.get("activeBaseColorSha256"),
        label="active base-color SHA-256",
    ) != candidate_sha:
        raise HighFidelityPackageAuditError(
            "HFN detail candidate hash is not the active appearanceTransfer base color"
        )

    image_index = _named_index(document, "images", HFN_IMAGE, label="HFN detail render payload")
    if image_index != 0:
        raise HighFidelityPackageAuditError(
            "HFN detail base color must remain canonical image 0"
        )
    image = _indexed(document, "images", image_index, label="HFN detail image")
    if image.get("mimeType") != "image/png":
        raise HighFidelityPackageAuditError("HFN detail active base color is not declared as PNG")
    textures = _array(document, "textures", label="HFN detail render payload")
    if not textures or not isinstance(textures[0], Mapping) or textures[0].get("source") != image_index:
        raise HighFidelityPackageAuditError(
            "HFN detail active image is not bound to canonical texture 0"
        )
    materials = _array(document, "materials", label="HFN detail render payload")
    if not materials or not isinstance(materials[0], Mapping):
        raise HighFidelityPackageAuditError("HFN detail requires canonical body material 0")
    pbr = materials[0].get("pbrMetallicRoughness")
    if not isinstance(pbr, Mapping) or pbr.get("baseColorTexture") != {"index": 0}:
        raise HighFidelityPackageAuditError(
            "HFN detail active image is not bound to body material 0 base color"
        )

    payload = _buffer_view_bytes(
        document,
        binary,
        image.get("bufferView"),
        label="HFN detail active base color",
    )
    if not payload.startswith(PNG_SIGNATURE):
        raise HighFidelityPackageAuditError("HFN detail active base-color bytes are not PNG")
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != candidate_sha:
        raise HighFidelityPackageAuditError(
            "HFN detail active base-color bytes do not match candidate authority"
        )
    return {
        "image": image_index,
        "buffer_view": image.get("bufferView"),
        "base_color_sha256": actual_sha,
        "method": method.strip(),
    }


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
    promotion = _require_promotion(
        bodyrig,
        "faceSecondaryPromotion",
        expected_format="bodyrig-face-secondary-promotion",
        component="face_secondary",
    )
    source_dental_raw = promotion.get("sourceDerivedDentalIdentity", False)
    generic_raw = promotion.get("genericSecondaryAnatomy", True)
    if type(source_dental_raw) is not bool or type(generic_raw) is not bool:
        raise HighFidelityPackageAuditError(
            "face_secondary dental source/generic disclosure is not boolean"
        )
    source_dental = source_dental_raw
    if generic_raw is source_dental:
        raise HighFidelityPackageAuditError(
            "face_secondary dental source/generic disclosure is inconsistent"
        )

    node_index, mesh_index, mesh = _require_scene_mesh(
        document,
        component="face_secondary",
        node_name=FACE_NODE,
        mesh_name=FACE_MESH,
    )
    required_face_materials = (
        ("BodyRigEyelashesReview",)
        if source_dental
        else FACE_MATERIALS
    )
    material_indexes = {
        name: _named_index(document, "materials", name, label="face_secondary render payload")
        for name in required_face_materials
    }
    used = _primitive_materials(mesh, component="face_secondary")
    if not set(material_indexes.values()).issubset(used):
        raise HighFidelityPackageAuditError(
            "face_secondary=complete but canonical secondary-face materials are not all used"
        )
    if source_dental:
        expected_lash_material = material_indexes["BodyRigEyelashesReview"]
        if used != {expected_lash_material}:
            raise HighFidelityPackageAuditError(
                "source-derived dental face mesh retained non-eyelash generic geometry"
            )
        face_primitives = mesh.get("primitives")
        if not isinstance(face_primitives, list) or len(face_primitives) != 2:
            raise HighFidelityPackageAuditError(
                "source-derived dental face mesh requires exactly two eyelash primitives"
            )
        expected_lash_roles = {"left_eyelashes", "right_eyelashes"}
        seen_lash_roles: set[str] = set()
        for primitive in face_primitives:
            extras = primitive.get("extras") if isinstance(primitive, Mapping) else None
            role = extras.get("bodyrigFaceSecondaryRole") if isinstance(extras, Mapping) else None
            if (
                role not in expected_lash_roles
                or role in seen_lash_roles
                or primitive.get("material") != expected_lash_material
            ):
                raise HighFidelityPackageAuditError(
                    "source-derived dental face eyelash role/material binding is invalid"
                )
            seen_lash_roles.add(str(role))
        if seen_lash_roles != expected_lash_roles:
            raise HighFidelityPackageAuditError(
                "source-derived dental face eyelash role set is incomplete"
            )
    result: dict[str, Any] = {
        "node": node_index,
        "mesh": mesh_index,
        "materials": material_indexes,
        "source_derived_dental_identity": source_dental,
    }
    if not source_dental:
        return result

    fine_requirement_raw = bodyrig.get("fineIdentityRequirement")
    try:
        fine_requirement = validate_fine_identity_requirement(fine_requirement_raw)
    except FineIdentityApplicationError as exc:
        raise HighFidelityPackageAuditError(
            f"source-derived dental payload lacks canonical fine-identity requirement: {exc}"
        ) from exc
    lineage = {
        "fineIdentityAttestationSha256": fine_requirement["fineIdentityAttestationSha256"],
        "fineIdentityAuthoritySha256": fine_requirement["fineIdentityAuthoritySha256"],
    }
    for field, expected in lineage.items():
        if promotion.get(field) != expected:
            raise HighFidelityPackageAuditError(
                f"source-derived dental promotion lost fine-identity lineage: {field}"
            )
    for field in ("dentalSourceVrmSha256", "dentalReconstructionResultSha256"):
        _canonical_sha256(
            promotion.get(field),
            label=f"source-derived dental {field}",
        )
    references = promotion.get("dentalSourceReferences")
    if (
        not isinstance(references, list)
        or len(references) < 2
        or any(not isinstance(item, str) or not item.strip() for item in references)
        or len(set(references)) != len(references)
    ):
        raise HighFidelityPackageAuditError(
            "source-derived dental promotion source references are invalid"
        )

    dental_node, dental_mesh_index, dental_mesh = _require_scene_mesh(
        document,
        component="source-derived dental",
        node_name=GRAFT_NODE_NAME,
        mesh_name=GRAFT_MESH_NAME,
    )
    dental_materials = {
        "mouth": _named_index(
            document,
            "materials",
            GRAFT_MOUTH_MATERIAL,
            label="source-derived dental render payload",
        ),
        "dental": _named_index(
            document,
            "materials",
            GRAFT_DENTAL_MATERIAL,
            label="source-derived dental render payload",
        ),
    }
    dental_used = _primitive_materials(dental_mesh, component="source-derived dental")
    if set(dental_materials.values()) != dental_used:
        raise HighFidelityPackageAuditError(
            "source-derived dental mesh uses non-canonical materials"
        )

    primitives = dental_mesh.get("primitives")
    if not isinstance(primitives, list):
        raise HighFidelityPackageAuditError(
            "source-derived dental mesh primitives are invalid"
        )
    expected_roles = {
        "mouth_interior": dental_materials["mouth"],
        "upper_teeth": dental_materials["dental"],
        "lower_teeth": dental_materials["dental"],
    }
    seen_roles: set[str] = set()
    for primitive in primitives:
        extras = primitive.get("extras") if isinstance(primitive, Mapping) else None
        role = extras.get("bodyrigDentalRole") if isinstance(extras, Mapping) else None
        if (
            role not in expected_roles
            or role in seen_roles
            or primitive.get("material") != expected_roles[role]
        ):
            raise HighFidelityPackageAuditError(
                "source-derived dental primitive role/material binding is invalid"
            )
        seen_roles.add(str(role))
    if seen_roles != set(expected_roles):
        raise HighFidelityPackageAuditError(
            "source-derived dental primitive role set is incomplete"
        )
    result["source_dental"] = {
        "node": dental_node,
        "mesh": dental_mesh_index,
        "materials": dental_materials,
        "roles": sorted(seen_roles),
        "source_references": list(references),
    }
    return result


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


def _apply_fine_identity_gate(
    fidelity: Mapping[str, Any],
    *,
    bodyrig: Mapping[str, Any],
    avatar_vrm: bytes,
) -> dict[str, Any]:
    result = dict(fidelity)
    result["top_level_blockers"] = list(fidelity.get("top_level_blockers") or [])
    fine_requirement_raw = bodyrig.get("fineIdentityRequirement")
    fine_application_raw = bodyrig.get("fineIdentityApplication")
    if fine_requirement_raw is None:
        if fine_application_raw is not None:
            raise HighFidelityPackageAuditError(
                "fine-identity application exists without a fine-identity requirement"
            )
        result["fine_identity_required"] = False
        result["fine_identity_ready"] = True
        result["fine_identity"] = None
        return result

    try:
        fine_requirement = validate_fine_identity_requirement(fine_requirement_raw)
    except FineIdentityApplicationError as exc:
        raise HighFidelityPackageAuditError(f"fine-identity requirement is invalid: {exc}") from exc

    fine_ready = False
    fine_application = None
    if fine_application_raw is not None:
        try:
            fine_application = validate_fine_identity_application(
                fine_application_raw,
                requirement=fine_requirement,
                avatar_vrm=avatar_vrm,
            )
        except FineIdentityApplicationError as exc:
            raise HighFidelityPackageAuditError(f"fine-identity application is invalid: {exc}") from exc
        fine_ready = True

    result["fine_identity_required"] = True
    result["fine_identity_ready"] = fine_ready
    result["fine_identity"] = {
        "requirement": fine_requirement,
        "application": fine_application,
    }
    if not fine_ready:
        result["high_fidelity_ready"] = False
        if "fine_identity" not in result["top_level_blockers"]:
            result["top_level_blockers"].append("fine_identity")
    return result


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

    document = _read_glb_document(avatar)
    fidelity = audit_fidelity_document(document)
    bodyrig = _bodyrig(document)

    fidelity = _apply_fine_identity_gate(
        fidelity,
        bodyrig=bodyrig,
        avatar_vrm=avatar,
    )

    if bodyrig.get("handsFeetNailsDetailApplication") is not None:
        hfn_payload = _audit_hfn_payload(document, _read_glb_binary(avatar), bodyrig)
        if hfn_payload is not None:
            fidelity["render_payloads"]["hands_feet_nails"] = hfn_payload
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