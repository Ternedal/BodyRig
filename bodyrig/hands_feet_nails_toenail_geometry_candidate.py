from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    _active_basecolor,
    read_detail_candidate,
)
from .hands_feet_nails_fingernail_geometry_candidate import (
    HandsFeetNailsFingernailGeometryError,
    _array,
    _body_geometry_inputs,
    _normalized_normal,
    _pack_f32,
    _pack_u16,
    _pack_u32,
    _package_avatar,
    _rewrite_package,
    _sha256_bytes,
    _sha256_file,
    _uv_evidence,
    read_fingernail_geometry_candidate,
)
from .hands_feet_nails_toenail_domain import (
    HandsFeetNailsToenailDomainError,
    toenail_triangle_groups,
)
from .hands_feet_nails_uv_domain_evidence import _canonical_mesh
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-hands-feet-nails-toenail-geometry-candidate"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-toenail-geometry-candidate-v1"
EMBEDDED_FORMAT = "bodyrig-hands-feet-nails-toenail-geometry"
NODE_NAME = "BodyRigToenailPlates"
MESH_NAME = "BodyRigToenailPlateMesh"
MATERIAL_NAME = "BodyRigToenailPlateMaterial"
OFFSET_METERS = 0.00070
GEOMETRY_ROOT = "hands-feet-nails-toenail-geometry-candidates"
TOE_LANDMARK_AUTHORITY = "source-big-small-heel-deterministic-five-toe-interpolation-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HandsFeetNailsToenailGeometryError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == VERSION


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


def _append_geometry(
    document: dict[str, Any],
    binary_bytes: bytes,
    *,
    uv_evidence: Mapping[str, Any],
    source_fingernail_package_sha256: str,
    uv_evidence_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    for array_name in ("bufferViews", "accessors", "materials", "meshes", "nodes", "scenes", "buffers"):
        _array(document, array_name)
    if any(
        isinstance(item, Mapping) and item.get("name") in {NODE_NAME, MESH_NAME, MATERIAL_NAME}
        for array_name in ("nodes", "meshes", "materials")
        for item in _array(document, array_name)
    ):
        raise HandsFeetNailsToenailGeometryError("toenail geometry is already present")
    if len(_array(document, "buffers")) != 1 or not isinstance(_array(document, "buffers")[0], dict):
        raise HandsFeetNailsToenailGeometryError("toenail geometry requires one embedded GLB buffer")
    scenes = _array(document, "scenes")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise HandsFeetNailsToenailGeometryError("toenail geometry requires canonical scene 0")

    _primitive, positions, normals, uvs, joints, weights, _indices_all, _joint_names = _body_geometry_inputs(document, binary_bytes)
    try:
        groups = toenail_triangle_groups(document, binary_bytes, uv_evidence)
    except HandsFeetNailsToenailDomainError as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc

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
                    raise HandsFeetNailsToenailGeometryError("body position tuple width is invalid")
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
                    raise HandsFeetNailsToenailGeometryError("body skinning tuple width is invalid")
                if any(value < 0 or value > 65535 for value in joint_row):
                    raise HandsFeetNailsToenailGeometryError("body joint index is outside unsigned-short range")
                plate_joints.append(joint_row)  # type: ignore[arg-type]
                plate_weights.append(weight_row)  # type: ignore[arg-type]
                plate_indices.append(len(plate_indices))
    if len(plate_triangle_counts) != 10 or not plate_positions or len(plate_positions) % 3:
        raise HandsFeetNailsToenailGeometryError("toenail plate geometry is incomplete or non-triangular")

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

    def add_accessor(
        raw: bytes,
        *,
        component_type: int,
        count: int,
        kind: str,
        target: int,
        bounds: list[tuple[float, ...]] | None = None,
    ) -> int:
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

    position_accessor = add_accessor(_pack_f32(plate_positions), component_type=5126, count=len(plate_positions), kind="VEC3", target=34962, bounds=plate_positions)
    normal_accessor = add_accessor(_pack_f32(plate_normals), component_type=5126, count=len(plate_normals), kind="VEC3", target=34962)
    uv_accessor = add_accessor(_pack_f32(plate_uvs), component_type=5126, count=len(plate_uvs), kind="VEC2", target=34962)
    joints_accessor = add_accessor(_pack_u16(plate_joints), component_type=5123, count=len(plate_joints), kind="VEC4", target=34962)
    weights_accessor = add_accessor(_pack_f32(plate_weights), component_type=5126, count=len(plate_weights), kind="VEC4", target=34962)
    index_accessor = add_accessor(_pack_u32(plate_indices), component_type=5125, count=len(plate_indices), kind="SCALAR", target=34963)

    materials.append({
        "name": MATERIAL_NAME,
        "doubleSided": False,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.0,
            "roughnessFactor": 0.30,
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
        raise HandsFeetNailsToenailGeometryError("toenail geometry requires BodyRig metadata")
    if not isinstance(bodyrig.get("handsFeetNailsFingernailGeometry"), Mapping):
        raise HandsFeetNailsToenailGeometryError("toenail geometry requires existing fingernail geometry authority")
    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "sourceFingernailPackageSha256": source_fingernail_package_sha256,
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
        "toeLandmarkAuthority": TOE_LANDMARK_AUTHORITY,
        "individualMiddleToeLandmarksObserved": False,
        "sourceGrounded": True,
        "additiveGeometryOnly": True,
        "geometryModified": True,
        "textureModified": False,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    bodyrig["handsFeetNailsToenailGeometry"] = embedded
    buffers[0]["byteLength"] = len(binary)
    try:
        result = _write_glb(document, bytes(binary))
    except PbrMaterialError as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    return result, embedded


def build_toenail_geometry_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    try:
        detail = read_detail_candidate(root_path, person_id, body_revision=body_revision, capture_id=capture_id, candidate_id=candidate_id)
        fingernail = read_fingernail_geometry_candidate(root_path, person_id, body_revision=body_revision, capture_id=capture_id, candidate_id=candidate_id)
    except (HandsFeetNailsDetailCandidateError, HandsFeetNailsFingernailGeometryError) as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    if fingernail.get("source_detail_package_sha256") != detail.get("candidate_package_sha256"):
        raise HandsFeetNailsToenailGeometryError("fingernail geometry no longer binds exact HFN detail package")
    source_package = Path(str(fingernail["package_path"])).expanduser().resolve()
    source_avatar, body_id = _package_avatar(source_package)
    if body_id != detail["body_id"] or _sha256_file(source_package) != fingernail["geometry_package_sha256"]:
        raise HandsFeetNailsToenailGeometryError("HFN fingernail geometry package identity changed")
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
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    mesh_index, skin_index, _primitive_index, _primitive, _joint_nodes, _joint_names = _canonical_mesh(document)
    if skin_index != 0:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry requires skin 0")
    base_mesh_before = copy.deepcopy(_array(document, "meshes")[mesh_index])
    base_skin_before = copy.deepcopy(_array(document, "skins")[skin_index])
    basecolor, _image, _views, _bodyrig, _appearance = _active_basecolor(document, binary, reject_existing_application=False)
    if _sha256_bytes(basecolor) != detail["candidate_basecolor_sha256"]:
        raise HandsFeetNailsToenailGeometryError("fingernail package changed HFN detail texture bytes")
    try:
        with Image.open(__import__("io").BytesIO(basecolor)) as image:
            width, height = image.size
    except (OSError, ValueError) as exc:
        raise HandsFeetNailsToenailGeometryError("HFN detail base color is unreadable") from exc
    if width < 64 or height < 64:
        raise HandsFeetNailsToenailGeometryError("HFN detail base color is too small for toenail geometry")

    geometry_avatar, embedded = _append_geometry(
        document,
        binary,
        uv_evidence=uv,
        source_fingernail_package_sha256=fingernail["geometry_package_sha256"],
        uv_evidence_sha256=detail["uv_evidence_sha256"],
    )
    try:
        after_document, after_binary = _read_glb(geometry_avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    after_mesh_index, after_skin_index, _p, _prim, _jn, _names = _canonical_mesh(after_document)
    if after_mesh_index != mesh_index or after_skin_index != skin_index:
        raise HandsFeetNailsToenailGeometryError("toenail geometry changed canonical body mesh/skin identity")
    if _array(after_document, "meshes")[mesh_index] != base_mesh_before:
        raise HandsFeetNailsToenailGeometryError("toenail geometry mutated canonical body mesh")
    if _array(after_document, "skins")[skin_index] != base_skin_before:
        raise HandsFeetNailsToenailGeometryError("toenail geometry mutated canonical SMPL-X skin")
    after_basecolor, _i, _v, _b, _a = _active_basecolor(after_document, after_binary, reject_existing_application=False)
    if _sha256_bytes(after_basecolor) != detail["candidate_basecolor_sha256"]:
        raise HandsFeetNailsToenailGeometryError("toenail geometry changed HFN detail texture bytes")

    package_out, receipt_out = geometry_paths(root_path, detail["person_id"], detail["body_revision"], detail["capture_id"], detail["candidate_id"])
    if package_out.exists() or receipt_out.exists():
        raise HandsFeetNailsToenailGeometryError("refusing to overwrite existing toenail geometry authority")
    package_created = False
    receipt_created = False
    try:
        _rewrite_package(source_package, package_out, avatar_vrm=geometry_avatar)
        package_created = True
        try:
            validated = validate_package(package_out)
        except MRBodyError as exc:
            raise HandsFeetNailsToenailGeometryError(f"toenail geometry package validation failed: {exc}") from exc
        if validated.manifest["id"] != body_id:
            raise HandsFeetNailsToenailGeometryError("toenail geometry changed canonical body id")
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
            "source_fingernail_receipt_sha256": _sha256_file(Path(str(fingernail["receipt_path"]))),
            "source_fingernail_package_sha256": fingernail["geometry_package_sha256"],
            "source_detail_package_sha256": detail["candidate_package_sha256"],
            "geometry_package_sha256": _sha256_file(package_out),
            "source_avatar_sha256": fingernail["geometry_avatar_sha256"],
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
            "toe_landmark_authority": TOE_LANDMARK_AUTHORITY,
            "individual_middle_toe_landmarks_observed": False,
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


def read_toenail_geometry_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    package_path, receipt_path = geometry_paths(root, person_id, body_revision, capture_id, candidate_id)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry receipt is unreadable") from exc
    if not isinstance(receipt, dict) or receipt.get("format") != FORMAT or not _is_v1(receipt.get("version")) or receipt.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry receipt format/version/policy mismatch")
    for field in (
        "source_fingernail_receipt_sha256", "source_fingernail_package_sha256", "source_detail_package_sha256",
        "geometry_package_sha256", "source_avatar_sha256", "geometry_avatar_sha256", "uv_evidence_sha256",
        "uv_evidence_path_sha256", "active_basecolor_sha256",
    ):
        value = str(receipt.get(field) or "").lower()
        if not SHA_RE.fullmatch(value):
            raise HandsFeetNailsToenailGeometryError(f"HFN toenail geometry {field} is invalid")
    if (
        receipt.get("node_name") != NODE_NAME
        or receipt.get("mesh_name") != MESH_NAME
        or receipt.get("material_name") != MATERIAL_NAME
        or receipt.get("plate_count") != 10
        or receipt.get("skin_index") != 0
        or receipt.get("offset_meters") != OFFSET_METERS
        or receipt.get("toe_landmark_authority") != TOE_LANDMARK_AUTHORITY
        or receipt.get("individual_middle_toe_landmarks_observed") is not False
        or receipt.get("source_grounded") is not True
        or receipt.get("additive_geometry_only") is not True
        or receipt.get("geometry_modified") is not True
        or receipt.get("texture_modified") is not False
        or receipt.get("human_review_required") is not True
        or receipt.get("production_activation") is not False
    ):
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry receipt authority is invalid")
    counts = receipt.get("plate_triangle_counts")
    if not isinstance(counts, Mapping) or len(counts) != 10 or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in counts.values()):
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry plate counts are invalid")
    if sum(int(value) for value in counts.values()) != receipt.get("triangle_count") or receipt.get("vertex_count") != int(receipt["triangle_count"]) * 3:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry triangle/vertex accounting is inconsistent")
    try:
        fingernail = read_fingernail_geometry_candidate(root, person_id, body_revision=body_revision, capture_id=capture_id, candidate_id=candidate_id)
    except HandsFeetNailsFingernailGeometryError as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    if (
        receipt.get("source_fingernail_package_sha256") != fingernail.get("geometry_package_sha256")
        or receipt.get("source_fingernail_receipt_sha256") != _sha256_file(Path(str(fingernail["receipt_path"])))
    ):
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry no longer binds exact fingernail geometry authority")
    if not package_path.is_file() or _sha256_file(package_path) != receipt["geometry_package_sha256"]:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry package bytes changed")
    avatar, body_id = _package_avatar(package_path)
    if body_id != receipt.get("body_id") or _sha256_bytes(avatar) != receipt["geometry_avatar_sha256"]:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry avatar/body identity changed")
    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsToenailGeometryError(str(exc)) from exc
    nodes = [item for item in _array(document, "nodes") if isinstance(item, Mapping) and item.get("name") == NODE_NAME]
    meshes = [item for item in _array(document, "meshes") if isinstance(item, Mapping) and item.get("name") == MESH_NAME]
    materials = [item for item in _array(document, "materials") if isinstance(item, Mapping) and item.get("name") == MATERIAL_NAME]
    if len(nodes) != 1 or len(meshes) != 1 or len(materials) != 1:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry render payload is missing or ambiguous")
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    embedded = bodyrig.get("handsFeetNailsToenailGeometry") if isinstance(bodyrig, Mapping) else None
    if (
        not isinstance(embedded, Mapping)
        or embedded.get("format") != EMBEDDED_FORMAT
        or not _is_v1(embedded.get("version"))
        or embedded.get("policyRevision") != POLICY_REVISION
        or embedded.get("sourceFingernailPackageSha256") != receipt["source_fingernail_package_sha256"]
        or embedded.get("toeLandmarkAuthority") != TOE_LANDMARK_AUTHORITY
        or embedded.get("individualMiddleToeLandmarksObserved") is not False
        or embedded.get("productionActivation") is not False
    ):
        raise HandsFeetNailsToenailGeometryError("embedded HFN toenail geometry authority is stale")
    basecolor, _i, _v, _b, _a = _active_basecolor(document, binary, reject_existing_application=False)
    if _sha256_bytes(basecolor) != receipt["active_basecolor_sha256"]:
        raise HandsFeetNailsToenailGeometryError("HFN toenail geometry active base color changed")
    return {**receipt, "package_path": str(package_path), "receipt_path": str(receipt_path)}
