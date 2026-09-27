from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    validate_landmark_evidence,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-hands-feet-nails-uv-domain-evidence"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-uv-domain-evidence-v1"
MESH_NAME = "BodyRigSourceDerivedMesh"
DONOR_MESH_NAME = "BodyRigSmplxDonorTopologyMesh"
MESH_NAMES = (MESH_NAME, DONOR_MESH_NAME)
SKIN_NAME = "SMPLX"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
WEIGHT_THRESHOLD = 0.20
REGION_JOINT_NAMES = {
    "left_hand": (
        "smplx_left_wrist",
        "smplx_left_index1", "smplx_left_index2", "smplx_left_index3",
        "smplx_left_middle1", "smplx_left_middle2", "smplx_left_middle3",
        "smplx_left_pinky1", "smplx_left_pinky2", "smplx_left_pinky3",
        "smplx_left_ring1", "smplx_left_ring2", "smplx_left_ring3",
        "smplx_left_thumb1", "smplx_left_thumb2", "smplx_left_thumb3",
    ),
    "right_hand": (
        "smplx_right_wrist",
        "smplx_right_index1", "smplx_right_index2", "smplx_right_index3",
        "smplx_right_middle1", "smplx_right_middle2", "smplx_right_middle3",
        "smplx_right_pinky1", "smplx_right_pinky2", "smplx_right_pinky3",
        "smplx_right_ring1", "smplx_right_ring2", "smplx_right_ring3",
        "smplx_right_thumb1", "smplx_right_thumb2", "smplx_right_thumb3",
    ),
    "left_foot": ("smplx_left_ankle", "smplx_left_foot"),
    "right_foot": ("smplx_right_ankle", "smplx_right_foot"),
}
SEMANTIC_REGIONS = {
    "left_hand": "left_fingernails",
    "right_hand": "right_fingernails",
    "left_foot": "left_toenails",
    "right_foot": "right_toenails",
}
TOP_FIELDS = {
    "format", "version", "policy_revision", "person_id", "body_revision", "capture_id",
    "landmark_evidence_bodyrig_revision", "uv_evidence_bodyrig_revision", "body_id",
    "package_sha256", "landmark_evidence_sha256", "mesh_name", "skin_name",
    "mesh_index", "skin_index", "primitive_index", "weight_threshold", "regions",
    "exact_source_package_bound", "geometry_modified", "texture_modified",
    "package_application_authority", "human_review_required", "production_activation",
}
REGION_FIELDS = {
    "capture_region", "semantic_region", "target_joint_names", "target_joint_indices",
    "vertex_count", "uv_count", "uv_bounds", "uv_set_sha256",
}


class HandsFeetNailsUvDomainEvidenceError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is not a canonical Git SHA")
    return text


def _int(value: Any, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is invalid")
    return value


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is non-finite")
    return result


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} must be a JSON object")
    return value


def _package_avatar(path: Path) -> tuple[bytes, str, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV source package is invalid") from exc
    return avatar, str(validated.manifest["id"]), _sha256_file(path)


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HandsFeetNailsUvDomainEvidenceError(f"glTF {name} array is missing")
    return value


def _indexed(array: list[Any], index: Any, *, label: str) -> dict[str, Any]:
    idx = _int(index, label=f"{label} index")
    if idx >= len(array) or not isinstance(array[idx], dict):
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} index is outside the glTF array")
    return array[idx]


def _accessor_values(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
    component_type: int,
    kind: str,
) -> list[tuple[float | int, ...]]:
    accessor = _indexed(_array(document, "accessors"), index, label=f"{label} accessor")
    if "sparse" in accessor or accessor.get("componentType") != component_type or accessor.get("type") != kind:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} accessor type is not canonical")
    count = _int(accessor.get("count"), label=f"{label} count", minimum=1)
    view = _indexed(_array(document, "bufferViews"), accessor.get("bufferView"), label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} accessor does not use GLB buffer 0")
    components = {"SCALAR": 1, "VEC2": 2, "VEC4": 4}.get(kind)
    formats = {5123: ("H", 2), 5126: ("f", 4)}
    if components is None or component_type not in formats:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} accessor component type is unsupported")
    code, width = formats[component_type]
    element_size = components * width
    view_offset = _int(view.get("byteOffset", 0), label=f"{label} view offset")
    view_length = _int(view.get("byteLength"), label=f"{label} view length", minimum=1)
    accessor_offset = _int(accessor.get("byteOffset", 0), label=f"{label} accessor offset")
    stride = _int(view.get("byteStride", element_size), label=f"{label} stride", minimum=element_size)
    view_end = view_offset + view_length
    start = view_offset + accessor_offset
    if view_end > len(binary) or start < view_offset:
        raise HandsFeetNailsUvDomainEvidenceError(f"{label} accessor exceeds GLB binary bytes")
    unpacker = struct.Struct("<" + code * components)
    result: list[tuple[float | int, ...]] = []
    for item in range(count):
        begin = start + item * stride
        end = begin + element_size
        if end > view_end:
            raise HandsFeetNailsUvDomainEvidenceError(f"{label} accessor exceeds its bufferView")
        result.append(tuple(unpacker.unpack(binary[begin:end])))
    return result


def _canonical_mesh(document: Mapping[str, Any]) -> tuple[int, int, int, dict[str, Any], list[int], list[str]]:
    meshes = _array(document, "meshes")
    mesh_matches = [
        index for index, item in enumerate(meshes)
        if isinstance(item, dict) and item.get("name") in MESH_NAMES
    ]
    if len(mesh_matches) != 1:
        raise HandsFeetNailsUvDomainEvidenceError("canonical source/donor body mesh is missing or ambiguous")
    mesh_index = mesh_matches[0]
    mesh = meshes[mesh_index]
    primitives = mesh.get("primitives")
    if not isinstance(primitives, list) or len(primitives) != 1 or not isinstance(primitives[0], dict):
        raise HandsFeetNailsUvDomainEvidenceError("canonical source/donor body mesh must contain one primitive")
    primitive = primitives[0]
    attrs = primitive.get("attributes")
    if not isinstance(attrs, dict) or not {"TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"} <= set(attrs):
        raise HandsFeetNailsUvDomainEvidenceError("canonical body primitive lacks UV/skinning attributes")

    skins = _array(document, "skins")
    skin_matches = [index for index, item in enumerate(skins) if isinstance(item, dict) and item.get("name") == SKIN_NAME]
    if len(skin_matches) != 1:
        raise HandsFeetNailsUvDomainEvidenceError("canonical SMPL-X skin is missing or ambiguous")
    skin_index = skin_matches[0]
    skin = skins[skin_index]
    joints = skin.get("joints")
    if not isinstance(joints, list) or not joints:
        raise HandsFeetNailsUvDomainEvidenceError("canonical SMPL-X skin joints are missing")
    nodes = _array(document, "nodes")
    joint_nodes: list[int] = []
    joint_names: list[str] = []
    for raw in joints:
        node_index = _int(raw, label="skin joint node")
        node = _indexed(nodes, node_index, label="skin joint node")
        name = str(node.get("name") or "")
        if not name or name in joint_names:
            raise HandsFeetNailsUvDomainEvidenceError("SMPL-X skin joint names are empty or ambiguous")
        joint_nodes.append(node_index)
        joint_names.append(name)
    bound_nodes = [
        node for node in nodes
        if isinstance(node, dict) and node.get("mesh") == mesh_index and node.get("skin") == skin_index
    ]
    if len(bound_nodes) != 1:
        raise HandsFeetNailsUvDomainEvidenceError("canonical body mesh is not bound exactly once to SMPL-X skin")
    return mesh_index, skin_index, 0, primitive, joint_nodes, joint_names


def _region_domain(
    *,
    capture_region: str,
    semantic_region: str,
    target_names: tuple[str, ...],
    joint_names: list[str],
    uvs: list[tuple[float | int, ...]],
    joints: list[tuple[float | int, ...]],
    weights: list[tuple[float | int, ...]],
) -> dict[str, Any]:
    missing = [name for name in target_names if name not in joint_names]
    if missing:
        raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} target joints are missing: {', '.join(missing)}")
    target_indices = [joint_names.index(name) for name in target_names]
    target_set = set(target_indices)
    if not (len(uvs) == len(joints) == len(weights)):
        raise HandsFeetNailsUvDomainEvidenceError("body UV/skinning accessor counts differ")
    selected: list[tuple[float, float]] = []
    for uv_raw, joint_raw, weight_raw in zip(uvs, joints, weights, strict=True):
        if len(uv_raw) != 2 or len(joint_raw) != 4 or len(weight_raw) != 4:
            raise HandsFeetNailsUvDomainEvidenceError("body UV/skinning tuple width is invalid")
        influences = [
            (int(joint_raw[index]), _number(weight_raw[index], label=f"{capture_region} skin weight"))
            for index in range(4)
        ]
        if any(weight < 0.0 or weight > 1.0 for _, weight in influences):
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} skin weight is outside 0..1")
        target_weight = sum(weight for joint, weight in influences if joint in target_set)
        if target_weight < WEIGHT_THRESHOLD:
            continue
        u = _number(uv_raw[0], label=f"{capture_region} u")
        v = _number(uv_raw[1], label=f"{capture_region} v")
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV is outside 0..1")
        selected.append((u, v))
    if len(selected) < 3:
        raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV domain contains too few skinned vertices")
    unique = sorted({(round(u, 8), round(v, 8)) for u, v in selected})
    if len(unique) < 3:
        raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV domain contains too few unique UVs")
    u_values = [item[0] for item in unique]
    v_values = [item[1] for item in unique]
    bounds = {"u_min": min(u_values), "v_min": min(v_values), "u_max": max(u_values), "v_max": max(v_values)}
    if bounds["u_max"] <= bounds["u_min"] or bounds["v_max"] <= bounds["v_min"]:
        raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV domain is degenerate")
    uv_payload = json.dumps(unique, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "capture_region": capture_region,
        "semantic_region": semantic_region,
        "target_joint_names": list(target_names),
        "target_joint_indices": target_indices,
        "vertex_count": len(selected),
        "uv_count": len(unique),
        "uv_bounds": bounds,
        "uv_set_sha256": _sha256_bytes(uv_payload),
    }


def validate_uv_domain_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV domain evidence fields are not canonical")
    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or version != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV domain evidence format/version/policy mismatch")
    person = str(value.get("person_id") or "").strip().lower()
    body = str(value.get("body_revision") or "").strip().lower()
    capture = str(value.get("capture_id") or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body) or not CAPTURE_RE.fullmatch(capture):
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV domain evidence identity is not canonical")
    landmark_revision = _revision(value.get("landmark_evidence_bodyrig_revision"), label="landmark evidence BodyRig revision")
    uv_revision = _revision(value.get("uv_evidence_bodyrig_revision"), label="UV evidence BodyRig revision")
    package_sha = _sha(value.get("package_sha256"), label="source package SHA-256")
    landmark_sha = _sha(value.get("landmark_evidence_sha256"), label="landmark evidence SHA-256")
    mesh_name = str(value.get("mesh_name") or "")
    if mesh_name not in MESH_NAMES or value.get("skin_name") != SKIN_NAME:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV mesh/skin authority mismatch")
    mesh_index = _int(value.get("mesh_index"), label="mesh index")
    skin_index = _int(value.get("skin_index"), label="skin index")
    primitive_index = _int(value.get("primitive_index"), label="primitive index")
    if value.get("weight_threshold") != WEIGHT_THRESHOLD:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV weight threshold changed")
    regions = value.get("regions")
    if not isinstance(regions, Mapping) or set(regions) != set(REGION_JOINT_NAMES):
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV region set is not canonical")
    normalized_regions: dict[str, dict[str, Any]] = {}
    for capture_region in REGION_JOINT_NAMES:
        item = regions.get(capture_region)
        if not isinstance(item, Mapping) or set(item) != REGION_FIELDS:
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV domain fields are not canonical")
        expected_names = list(REGION_JOINT_NAMES[capture_region])
        if item.get("capture_region") != capture_region or item.get("semantic_region") != SEMANTIC_REGIONS[capture_region]:
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV domain scope mismatch")
        if item.get("target_joint_names") != expected_names:
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV joint-name authority mismatch")
        indices = item.get("target_joint_indices")
        if (
            not isinstance(indices, list)
            or len(indices) != len(expected_names)
            or any(isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in indices)
            or len(set(indices)) != len(indices)
        ):
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV joint indices are invalid")
        vertex_count = _int(item.get("vertex_count"), label=f"{capture_region} vertex count", minimum=3)
        uv_count = _int(item.get("uv_count"), label=f"{capture_region} UV count", minimum=3)
        if uv_count > vertex_count:
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV count exceeds vertex count")
        bounds = item.get("uv_bounds")
        if not isinstance(bounds, Mapping) or set(bounds) != {"u_min", "v_min", "u_max", "v_max"}:
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV bounds are invalid")
        u_min = _number(bounds.get("u_min"), label=f"{capture_region} u_min")
        v_min = _number(bounds.get("v_min"), label=f"{capture_region} v_min")
        u_max = _number(bounds.get("u_max"), label=f"{capture_region} u_max")
        v_max = _number(bounds.get("v_max"), label=f"{capture_region} v_max")
        if not (0.0 <= u_min < u_max <= 1.0 and 0.0 <= v_min < v_max <= 1.0):
            raise HandsFeetNailsUvDomainEvidenceError(f"{capture_region} UV bounds are outside 0..1")
        _sha(item.get("uv_set_sha256"), label=f"{capture_region} UV-set SHA-256")
        normalized_regions[capture_region] = dict(item)
    if (
        value.get("exact_source_package_bound") is not True
        or value.get("geometry_modified") is not False
        or value.get("texture_modified") is not False
        or value.get("package_application_authority") is not False
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV domain evidence crossed its evidence-only authority boundary")
    body_id = str(value.get("body_id") or "").strip()
    if not body_id:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV body id is missing")
    return {
        **dict(value),
        "person_id": person,
        "body_revision": body,
        "capture_id": capture,
        "landmark_evidence_bodyrig_revision": landmark_revision,
        "uv_evidence_bodyrig_revision": uv_revision,
        "body_id": body_id,
        "package_sha256": package_sha,
        "landmark_evidence_sha256": landmark_sha,
        "mesh_name": mesh_name,
        "mesh_index": mesh_index,
        "skin_index": skin_index,
        "primitive_index": primitive_index,
        "regions": normalized_regions,
    }


def evidence_path(
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    uv_bodyrig_revision: str,
) -> Path:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    revision = _revision(uv_bodyrig_revision, label="UV evidence BodyRig revision")
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body) or not CAPTURE_RE.fullmatch(capture):
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV evidence path identity is invalid")
    return Path(root).expanduser().resolve() / "hands-feet-nails-uv-domain-evidence" / person / body / capture / f"{revision}.json"


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise HandsFeetNailsUvDomainEvidenceError(f"HFN UV domain evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def derive_uv_domain_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    landmark_evidence_path: str | os.PathLike[str],
    package_path: str | os.PathLike[str],
    uv_bodyrig_revision: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    uv_revision = _revision(uv_bodyrig_revision, label="UV evidence BodyRig revision")

    landmark_path = Path(landmark_evidence_path).expanduser().resolve()
    landmark_raw = _read_json(landmark_path, label="HFN landmark evidence")
    try:
        landmark = validate_landmark_evidence(landmark_raw)
    except HandsFeetNailsLandmarkEvidenceError as exc:
        raise HandsFeetNailsUvDomainEvidenceError(str(exc)) from exc
    if landmark["person_id"] != person or landmark["body_revision"] != body or landmark["capture_id"] != capture:
        raise HandsFeetNailsUvDomainEvidenceError("HFN landmark evidence belongs to a different Person/body/capture")
    if landmark.get("all_regions_application_ready") is not True:
        raise HandsFeetNailsUvDomainEvidenceError("HFN UV derivation fails closed until all landmark regions are application-ready")
    landmark_sha = _sha256_file(landmark_path)

    package = Path(package_path).expanduser().resolve()
    avatar, body_id, package_sha = _package_avatar(package)
    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsUvDomainEvidenceError(f"HFN UV source avatar is invalid GLB: {exc}") from exc
    mesh_index, skin_index, primitive_index, primitive, _joint_nodes, joint_names = _canonical_mesh(document)
    meshes = _array(document, "meshes")
    mesh_name = str(meshes[mesh_index].get("name") or "")
    attrs = primitive["attributes"]
    uvs = _accessor_values(document, binary, attrs["TEXCOORD_0"], label="body TEXCOORD_0", component_type=5126, kind="VEC2")
    joints = _accessor_values(document, binary, attrs["JOINTS_0"], label="body JOINTS_0", component_type=5123, kind="VEC4")
    weights = _accessor_values(document, binary, attrs["WEIGHTS_0"], label="body WEIGHTS_0", component_type=5126, kind="VEC4")
    regions = {
        capture_region: _region_domain(
            capture_region=capture_region,
            semantic_region=SEMANTIC_REGIONS[capture_region],
            target_names=REGION_JOINT_NAMES[capture_region],
            joint_names=joint_names,
            uvs=uvs,
            joints=joints,
            weights=weights,
        )
        for capture_region in REGION_JOINT_NAMES
    }
    value = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "person_id": person,
        "body_revision": body,
        "capture_id": capture,
        "landmark_evidence_bodyrig_revision": landmark["evidence_bodyrig_revision"],
        "uv_evidence_bodyrig_revision": uv_revision,
        "body_id": body_id,
        "package_sha256": package_sha,
        "landmark_evidence_sha256": landmark_sha,
        "mesh_name": mesh_name,
        "skin_name": SKIN_NAME,
        "mesh_index": mesh_index,
        "skin_index": skin_index,
        "primitive_index": primitive_index,
        "weight_threshold": WEIGHT_THRESHOLD,
        "regions": regions,
        "exact_source_package_bound": True,
        "geometry_modified": False,
        "texture_modified": False,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }
    validated = validate_uv_domain_evidence(value)
    output = evidence_path(root_path, person, body, capture, uv_revision)
    _write_create_only(output, validated)
    return {**validated, "manifest": str(output)}
