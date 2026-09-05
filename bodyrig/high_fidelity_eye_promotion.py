from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import FidelityComponentError, validate_receipt, with_component_status
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .high_fidelity_eye_runtime_fingerprint import (
    CORNEA_MATERIAL_NAME,
    EYE_MESH_NAME,
    EYE_NODE_NAME,
    PRIMITIVE_ROLES,
    SOURCE_IMAGE_NAME,
    SOURCE_MATERIAL_NAME,
    HighFidelityEyeRuntimeFingerprintError,
    semantic_eye_runtime_fingerprint,
)
from .high_fidelity_eye_runtime_rebuild import (
    BRIDGE_RESULT_NAME,
    PREPARATION_NAME,
    RECEIPT_NAME as REBUILD_RECEIPT_NAME,
    REVIEW_VRM_NAME,
    HighFidelityEyeRuntimeRebuildError,
    read_rebuild,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .package import MRBodyError, validate_package
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-eye-promotion"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-eye-promotion-v1"
EMBEDDED_FORMAT = "bodyrig-eye-promotion"
PROMOTION_ROOT = ".high-fidelity-eye-promotions"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
ANATOMY_FORMAT = "bodyrig-body-anatomy-promotion"
HAIR_FORMAT = "bodyrig-hair-promotion"


class HighFidelityEyePromotionError(RuntimeError):
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
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityEyePromotionError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityEyePromotionError(f"{label} is not a canonical Git SHA")
    return clean


def _job(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityEyePromotionError("high-fidelity preview job id is not canonical")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityEyePromotionError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityEyePromotionError(f"{label} must be a JSON object")
    return value


def _package_avatar(path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityEyePromotionError(f"package is invalid or lacks avatar.vrm: {path}") from exc
    return avatar, str(validated.manifest["id"])


def _bodyrig(document: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HighFidelityEyePromotionError(f"{label} lacks BodyRig metadata")
    return bodyrig


def _assert_destination_lineage(
    document: Mapping[str, Any],
    *,
    source_candidate_sha: str,
    canonical_body_id: str,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    bodyrig = _bodyrig(document, label="promotion destination avatar")
    if "eyePromotion" in bodyrig or "eyeReviewRuntime" in bodyrig:
        raise HighFidelityEyePromotionError("promotion destination already contains eye promotion/review runtime authority")
    raw = bodyrig.get("fidelityComponents")
    if not isinstance(raw, Mapping):
        raise HighFidelityEyePromotionError("promotion destination lacks fidelity component receipt")
    try:
        before = validate_receipt(raw)
    except FidelityComponentError as exc:
        raise HighFidelityEyePromotionError(str(exc)) from exc
    if before["components"].get("body_anatomy") != "complete":
        raise HighFidelityEyePromotionError("eye promotion requires body_anatomy=complete in destination package")
    if before["components"].get("eyes") == "complete":
        raise HighFidelityEyePromotionError("eyes are already complete in destination package")

    anatomy = bodyrig.get("bodyAnatomyPromotion")
    if not isinstance(anatomy, dict):
        raise HighFidelityEyePromotionError("destination body_anatomy=complete lacks embedded anatomy promotion authority")
    if (
        anatomy.get("format") != ANATOMY_FORMAT
        or anatomy.get("version") != 1
        or anatomy.get("component") != "body_anatomy"
        or anatomy.get("sourcePackageSha256") != source_candidate_sha
        or anatomy.get("productionActivation") is not False
    ):
        raise HighFidelityEyePromotionError("destination anatomy promotion does not trace to the reviewed candidate")

    hair_complete = before["components"].get("hair") == "complete"
    hair = bodyrig.get("hairPromotion")
    if hair_complete:
        if not isinstance(hair, dict):
            raise HighFidelityEyePromotionError("destination hair=complete lacks embedded hair promotion authority")
        required_hair_fields = {
            "format", "version", "policyRevision", "previewJobId", "sourceBodyRigRevision",
            "promotionBodyRigRevision", "targetFamily", "sourceCandidatePackageSha256",
            "anatomyPromotedPackageSha256", "anatomyPromotionReceiptSha256",
            "hairDeformationReviewSha256", "combinedBridgeResultSha256", "rebuiltHairBridgeSha256",
            "rebuiltHairRuntimeReceiptSha256", "rebuiltHairReviewVrmSha256", "component",
            "eyesImported", "productionActivation",
        }
        if set(hair) != required_hair_fields:
            raise HighFidelityEyePromotionError("destination embedded hair promotion fields are not canonical")
        if (
            hair.get("format") != HAIR_FORMAT
            or hair.get("version") != 1
            or hair.get("component") != "hair"
            or hair.get("sourceCandidatePackageSha256") != source_candidate_sha
            or hair.get("eyesImported") is not False
            or hair.get("productionActivation") is not False
        ):
            raise HighFidelityEyePromotionError("destination hair promotion does not trace cleanly to the reviewed candidate")
        for field in (
            "anatomyPromotedPackageSha256", "anatomyPromotionReceiptSha256", "hairDeformationReviewSha256",
            "combinedBridgeResultSha256", "rebuiltHairBridgeSha256", "rebuiltHairRuntimeReceiptSha256",
            "rebuiltHairReviewVrmSha256",
        ):
            _sha(hair.get(field), label=f"destination hair promotion {field}")
        _revision(hair.get("sourceBodyRigRevision"), label="destination hair source revision")
        _revision(hair.get("promotionBodyRigRevision"), label="destination hair promotion revision")
    elif hair is not None:
        raise HighFidelityEyePromotionError("destination carries hairPromotion metadata while hair is not complete")

    for node in document.get("nodes", []) if isinstance(document.get("nodes"), list) else []:
        if isinstance(node, Mapping) and str(node.get("name") or "") == EYE_NODE_NAME:
            raise HighFidelityEyePromotionError("destination already contains canonical eye runtime geometry")
    for material in document.get("materials", []) if isinstance(document.get("materials"), list) else []:
        if isinstance(material, Mapping) and str(material.get("name") or "") in {SOURCE_MATERIAL_NAME, CORNEA_MATERIAL_NAME}:
            raise HighFidelityEyePromotionError("destination already contains canonical eye runtime materials")
    for image in document.get("images", []) if isinstance(document.get("images"), list) else []:
        if isinstance(image, Mapping) and str(image.get("name") or "") == SOURCE_IMAGE_NAME:
            raise HighFidelityEyePromotionError("destination already contains canonical source-eye image")
    return bodyrig, before, hair_complete


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HighFidelityEyePromotionError(f"glTF {name} array is missing")
    return value


def _indexed(array: list[Any], index: Any, *, label: str) -> dict[str, Any]:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(array) or not isinstance(array[index], dict):
        raise HighFidelityEyePromotionError(f"{label} index is invalid")
    return array[index]


def _view_bytes(document: Mapping[str, Any], binary: bytes, index: Any, *, label: str) -> bytes:
    view = _indexed(_array(document, "bufferViews"), index, label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HighFidelityEyePromotionError(f"{label} does not use the canonical GLB buffer")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise HighFidelityEyePromotionError(f"{label} bufferView range is invalid")
    if offset + length > len(binary):
        raise HighFidelityEyePromotionError(f"{label} bufferView exceeds binary bytes")
    return binary[offset:offset + length]


def _accessor_tight_bytes(document: Mapping[str, Any], binary: bytes, index: int, *, label: str) -> tuple[dict[str, Any], bytes]:
    accessors = _array(document, "accessors")
    views = _array(document, "bufferViews")
    accessor = _indexed(accessors, index, label=f"{label} accessor")
    if "sparse" in accessor or "bufferView" not in accessor:
        raise HighFidelityEyePromotionError(f"{label} accessor is not canonical tight-copy input")
    component = accessor.get("componentType")
    kind = accessor.get("type")
    count = accessor.get("count")
    component_size = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}.get(component)
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}.get(kind)
    if component_size is None or width is None or isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise HighFidelityEyePromotionError(f"{label} accessor type/count is invalid")
    view = _indexed(views, accessor["bufferView"], label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HighFidelityEyePromotionError(f"{label} accessor uses noncanonical buffer")
    view_offset = view.get("byteOffset", 0)
    view_length = view.get("byteLength")
    accessor_offset = accessor.get("byteOffset", 0)
    element_size = component_size * width
    stride = view.get("byteStride", element_size)
    for value, field in ((view_offset, "view offset"), (view_length, "view length"), (accessor_offset, "accessor offset"), (stride, "stride")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HighFidelityEyePromotionError(f"{label} {field} is invalid")
    if view_length < 1 or stride < element_size or view_offset + view_length > len(binary):
        raise HighFidelityEyePromotionError(f"{label} accessor range is invalid")
    start = view_offset + accessor_offset
    end_view = view_offset + view_length
    tight = bytearray()
    for item in range(count):
        begin = start + item * stride
        end = begin + element_size
        if end > end_view:
            raise HighFidelityEyePromotionError(f"{label} accessor exceeds its bufferView")
        tight.extend(binary[begin:end])
    copied: dict[str, Any] = {
        "componentType": component,
        "count": count,
        "type": kind,
    }
    if accessor.get("normalized") is True:
        copied["normalized"] = True
    for field in ("min", "max"):
        if field in accessor:
            copied[field] = accessor[field]
    return copied, bytes(tight)


def _assert_skeleton_compatible(source: Mapping[str, Any], destination: Mapping[str, Any]) -> None:
    source_skins = _array(source, "skins")
    dest_skins = _array(destination, "skins")
    if not source_skins or not dest_skins:
        raise HighFidelityEyePromotionError("eye promotion requires skin 0 in source and destination")
    source_skin = _indexed(source_skins, 0, label="source skin 0")
    dest_skin = _indexed(dest_skins, 0, label="destination skin 0")
    source_joints = source_skin.get("joints")
    dest_joints = dest_skin.get("joints")
    if not isinstance(source_joints, list) or not isinstance(dest_joints, list) or len(source_joints) != len(dest_joints):
        raise HighFidelityEyePromotionError("source/destination skin joint counts differ")
    source_nodes = _array(source, "nodes")
    dest_nodes = _array(destination, "nodes")
    for position, (source_index, dest_index) in enumerate(zip(source_joints, dest_joints)):
        source_node = _indexed(source_nodes, source_index, label=f"source skin joint {position}")
        dest_node = _indexed(dest_nodes, dest_index, label=f"destination skin joint {position}")
        if source_node.get("name") != dest_node.get("name"):
            raise HighFidelityEyePromotionError("source/destination skin joint ordering differs")
    source_bodyrig = _bodyrig(source, label="eye-only runtime")
    dest_bodyrig = _bodyrig(destination, label="promotion destination")
    if source_bodyrig.get("sourceGeometryAuthority") != dest_bodyrig.get("sourceGeometryAuthority"):
        raise HighFidelityEyePromotionError("eye-only runtime and destination source geometry authority differ")


def graft_eye_stage(destination_vrm: bytes, eye_only_vrm: bytes) -> bytes:
    try:
        destination, destination_binary_raw = _read_glb(destination_vrm)
        source, source_binary = _read_glb(eye_only_vrm)
    except PbrMaterialError as exc:
        raise HighFidelityEyePromotionError(str(exc)) from exc
    _assert_skeleton_compatible(source, destination)

    source_nodes = _array(source, "nodes")
    matches = [item for item in source_nodes if isinstance(item, dict) and item.get("name") == EYE_NODE_NAME]
    if len(matches) != 1:
        raise HighFidelityEyePromotionError("eye-only runtime canonical eye node is missing or ambiguous")
    source_node = matches[0]
    source_mesh = _indexed(_array(source, "meshes"), source_node.get("mesh"), label="source eye mesh")
    if source_mesh.get("name") != EYE_MESH_NAME or not isinstance(source_mesh.get("primitives"), list) or len(source_mesh["primitives"]) != len(PRIMITIVE_ROLES):
        raise HighFidelityEyePromotionError("eye-only runtime mesh/primitive contract is invalid")

    destination_binary = bytearray(destination_binary_raw)
    dest_views = _array(destination, "bufferViews")
    dest_accessors = _array(destination, "accessors")
    dest_images = _array(destination, "images")
    dest_textures = _array(destination, "textures")
    dest_materials = _array(destination, "materials")
    dest_meshes = _array(destination, "meshes")
    dest_nodes = _array(destination, "nodes")
    dest_samplers = _array(destination, "samplers")
    dest_scenes = _array(destination, "scenes")
    dest_buffers = _array(destination, "buffers")
    if not dest_scenes or not isinstance(dest_scenes[0], dict) or not isinstance(dest_scenes[0].get("nodes"), list):
        raise HighFidelityEyePromotionError("destination scene 0 is invalid")
    if len(dest_buffers) != 1 or not isinstance(dest_buffers[0], dict):
        raise HighFidelityEyePromotionError("destination GLB buffer contract is invalid")

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(destination_binary) % 4:
            destination_binary.append(0)
        offset = len(destination_binary)
        destination_binary.extend(raw)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        dest_views.append(view)
        return len(dest_views) - 1

    def copy_accessor(index: int, *, label: str, target: int) -> int:
        metadata, raw = _accessor_tight_bytes(source, source_binary, index, label=label)
        metadata["bufferView"] = add_view(raw, target=target)
        dest_accessors.append(metadata)
        return len(dest_accessors) - 1

    source_materials = _array(source, "materials")
    source_images = _array(source, "images")
    source_textures = _array(source, "textures")
    source_samplers = _array(source, "samplers")
    source_surface = next((item for item in source_materials if isinstance(item, dict) and item.get("name") == SOURCE_MATERIAL_NAME), None)
    source_cornea = next((item for item in source_materials if isinstance(item, dict) and item.get("name") == CORNEA_MATERIAL_NAME), None)
    source_image = next((item for item in source_images if isinstance(item, dict) and item.get("name") == SOURCE_IMAGE_NAME), None)
    if not isinstance(source_surface, dict) or not isinstance(source_cornea, dict) or not isinstance(source_image, dict):
        raise HighFidelityEyePromotionError("eye-only runtime source image/material authority is incomplete")
    pbr = source_surface.get("pbrMetallicRoughness")
    texture_info = pbr.get("baseColorTexture") if isinstance(pbr, dict) else None
    if not isinstance(texture_info, dict) or not isinstance(texture_info.get("index"), int):
        raise HighFidelityEyePromotionError("eye-only source surface texture reference is invalid")
    source_texture = _indexed(source_textures, texture_info["index"], label="source eye texture")
    source_sampler = _indexed(source_samplers, source_texture.get("sampler"), label="source eye sampler")
    source_image_bytes = _view_bytes(source, source_binary, source_image.get("bufferView"), label="source eye image")

    sampler_copy = dict(source_sampler)
    dest_samplers.append(sampler_copy)
    sampler_index = len(dest_samplers) - 1
    image_copy = {"name": SOURCE_IMAGE_NAME, "bufferView": add_view(source_image_bytes), "mimeType": "image/png"}
    dest_images.append(image_copy)
    image_index = len(dest_images) - 1
    texture_copy = {"sampler": sampler_index, "source": image_index}
    dest_textures.append(texture_copy)
    texture_index = len(dest_textures) - 1

    surface_copy = json.loads(json.dumps(source_surface))
    surface_copy["pbrMetallicRoughness"]["baseColorTexture"]["index"] = texture_index
    dest_materials.append(surface_copy)
    surface_index = len(dest_materials) - 1
    cornea_copy = json.loads(json.dumps(source_cornea))
    dest_materials.append(cornea_copy)
    cornea_index = len(dest_materials) - 1

    copied_primitives: list[dict[str, Any]] = []
    for role, primitive in zip(PRIMITIVE_ROLES, source_mesh["primitives"]):
        if not isinstance(primitive, dict) or primitive.get("mode") != 4 or not isinstance(primitive.get("attributes"), dict):
            raise HighFidelityEyePromotionError(f"source {role} primitive is invalid")
        attrs = primitive["attributes"]
        expected_attrs = {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
        if set(attrs) != expected_attrs:
            raise HighFidelityEyePromotionError(f"source {role} primitive attributes are invalid")
        copied_attrs = {
            semantic: copy_accessor(int(attrs[semantic]), label=f"{role} {semantic}", target=34962)
            for semantic in ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0")
        }
        copied_indices = copy_accessor(int(primitive["indices"]), label=f"{role} indices", target=34963)
        material_index = cornea_index if role.endswith("cornea") else surface_index
        copied_primitives.append({"attributes": copied_attrs, "indices": copied_indices, "material": material_index, "mode": 4})

    dest_meshes.append({"name": EYE_MESH_NAME, "primitives": copied_primitives})
    mesh_index = len(dest_meshes) - 1
    dest_nodes.append({"name": EYE_NODE_NAME, "mesh": mesh_index, "skin": 0})
    dest_scenes[0]["nodes"].append(len(dest_nodes) - 1)

    source_eye_metadata = _bodyrig(source, label="eye-only runtime").get("eyeReviewRuntime")
    if not isinstance(source_eye_metadata, dict):
        raise HighFidelityEyePromotionError("eye-only runtime lacks eyeReviewRuntime metadata")
    dest_bodyrig = _bodyrig(destination, label="promotion destination")
    dest_bodyrig["eyeReviewRuntime"] = json.loads(json.dumps(source_eye_metadata))
    dest_buffers[0]["byteLength"] = len(destination_binary)
    return _write_glb(destination, bytes(destination_binary))


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityEyePromotionError("could not read destination source package") from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise HighFidelityEyePromotionError("destination source package lacks canonical avatar/checksum files")
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HighFidelityEyePromotionError(f"refusing to overwrite promoted eye package: {destination}") from exc
    except OSError as exc:
        raise HighFidelityEyePromotionError("could not write promoted eye package") from exc


def _validated_rebuild(
    preview_job_id: str,
    *,
    candidate_package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    eye_runtime_dir: str | Path,
    bridge_script_sha256: str,
) -> tuple[dict[str, Any], Path, Path, str]:
    runtime_root = Path(eye_runtime_dir).expanduser().resolve()
    if not runtime_root.is_dir():
        raise HighFidelityEyePromotionError("fingerprint-matched eye-only runtime directory is missing")
    try:
        value = read_rebuild(
            preview_job_id,
            package_path=candidate_package_path,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
            staging_dir=runtime_root,
            bridge_script_sha256=bridge_script_sha256,
        )
    except HighFidelityEyeRuntimeRebuildError as exc:
        raise HighFidelityEyePromotionError(f"eye-only rebuild authority failed: {exc}") from exc
    if (
        value.get("fingerprintMatch") is not True
        or value.get("sourceHairRuntimeImported") is not False
        or value.get("eyeOnlyRuntimeVerified") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("eyesPromoted") is not False
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyePromotionError("eye-only rebuild crossed its non-materializing authority boundary")
    vrm_path = Path(str(value.get("rebuiltVrmPath") or "")).expanduser().resolve()
    receipt_path = Path(str(value.get("rebuildReceiptPath") or "")).expanduser().resolve()
    if not vrm_path.is_file() or not receipt_path.is_file():
        raise HighFidelityEyePromotionError("eye-only rebuild evidence disappeared after validation")
    return value, vrm_path, receipt_path, _sha256_file(receipt_path)


def _promotion_root(preview_job_id: str, *, target_sha: str, rebuild_sha: str) -> Path:
    return ui_jobs_dir() / PROMOTION_ROOT / _job(preview_job_id) / f"{target_sha}.{rebuild_sha}.eyes"


def write_promotion(
    preview_job_id: str,
    *,
    candidate_package_path: str | Path,
    target_package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    eye_runtime_dir: str | Path,
    bridge_script_sha256: str,
    promotion_bodyrig_revision: str,
) -> dict[str, Any]:
    promotion_revision = _revision(promotion_bodyrig_revision, label="eye promotion BodyRig revision")
    rebuild, eye_vrm_path, rebuild_receipt_path, rebuild_receipt_sha = _validated_rebuild(
        preview_job_id,
        candidate_package_path=candidate_package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        eye_runtime_dir=eye_runtime_dir,
        bridge_script_sha256=bridge_script_sha256,
    )
    source_candidate_sha = _sha(rebuild["candidatePackageSha256"], label="reviewed candidate package SHA")
    source_fingerprint_sha = _sha(rebuild["sourceFingerprintSha256"], label="reviewed eye fingerprint SHA")
    if rebuild.get("rebuiltFingerprintSha256") != source_fingerprint_sha:
        raise HighFidelityEyePromotionError("eye-only rebuild fingerprint equality changed before promotion")

    target = Path(target_package_path).expanduser().resolve()
    if not target.is_file():
        raise HighFidelityEyePromotionError(f"promotion destination source package is missing: {target}")
    target_sha = _sha256_file(target)
    target_avatar, body_id = _package_avatar(target)
    if body_id != rebuild.get("canonicalBodyId"):
        raise HighFidelityEyePromotionError("promotion destination body id differs from reviewed eye authority")
    try:
        target_audit = audit_high_fidelity_package(target)
        target_document, _target_binary = _read_glb(target_avatar)
    except (HighFidelityPackageAuditError, PbrMaterialError) as exc:
        raise HighFidelityEyePromotionError(f"promotion destination failed high-fidelity audit: {exc}") from exc
    target_bodyrig, before, hair_complete = _assert_destination_lineage(
        target_document,
        source_candidate_sha=source_candidate_sha,
        canonical_body_id=body_id,
    )
    if target_audit["components"] != before["components"] or target_audit["production_ready"] is not False:
        raise HighFidelityEyePromotionError("promotion destination component audit differs from embedded authority")

    eye_only_vrm = eye_vrm_path.read_bytes()
    grafted = graft_eye_stage(target_avatar, eye_only_vrm)
    try:
        graft_fingerprint = semantic_eye_runtime_fingerprint(grafted)
    except HighFidelityEyeRuntimeFingerprintError as exc:
        raise HighFidelityEyePromotionError(f"grafted eye runtime fingerprint failed: {exc}") from exc
    if graft_fingerprint.get("fingerprintSha256") != source_fingerprint_sha:
        raise HighFidelityEyePromotionError("grafted destination eye stage differs from reviewed fingerprint")

    try:
        promoted_document, promoted_binary = _read_glb(grafted)
    except PbrMaterialError as exc:
        raise HighFidelityEyePromotionError(str(exc)) from exc
    promoted_bodyrig = _bodyrig(promoted_document, label="grafted destination")
    if promoted_bodyrig.get("fidelityComponents") != target_bodyrig.get("fidelityComponents"):
        raise HighFidelityEyePromotionError("eye graft changed component authority before explicit promotion")
    try:
        after = with_component_status(before, component="eyes", status="complete")
    except FidelityComponentError as exc:
        raise HighFidelityEyePromotionError(str(exc)) from exc
    for component, status in before["components"].items():
        if component != "eyes" and after["components"].get(component) != status:
            raise HighFidelityEyePromotionError("eye promotion attempted to change another fidelity component")

    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": _job(preview_job_id),
        "promotionBodyRigRevision": promotion_revision,
        "canonicalBodyId": body_id,
        "sourceCandidatePackageSha256": source_candidate_sha,
        "destinationSourcePackageSha256": target_sha,
        "eyeRuntimeRebuildReceiptSha256": rebuild_receipt_sha,
        "eyeRuntimeBridgeScriptSha256": _sha(bridge_script_sha256, label="eye-only bridge script SHA"),
        "reviewedEyeFingerprintSha256": source_fingerprint_sha,
        "rebuiltEyeReviewVrmSha256": _sha(rebuild["rebuiltReviewVrmSha256"], label="rebuilt eye review VRM SHA"),
        "hairCompletePreserved": hair_complete,
        "component": "eyes",
        "sourceEyeRuntimeImported": True,
        "sourceHairRuntimeImported": False,
        "productionActivation": False,
    }
    promoted_bodyrig["fidelityComponents"] = after
    promoted_bodyrig["eyePromotion"] = embedded
    promoted_avatar = _write_glb(promoted_document, promoted_binary)
    final_fingerprint = semantic_eye_runtime_fingerprint(promoted_avatar)
    if final_fingerprint.get("fingerprintSha256") != source_fingerprint_sha:
        raise HighFidelityEyePromotionError("embedded eye promotion metadata changed canonical eye-stage fingerprint")

    final_root = _promotion_root(preview_job_id, target_sha=target_sha, rebuild_sha=rebuild_receipt_sha)
    if final_root.exists():
        raise HighFidelityEyePromotionError(f"refusing to overwrite existing eye promotion authority: {final_root}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    staging = final_root.with_name(f".{final_root.name}.partial-{uuid.uuid4().hex}")
    staging.mkdir()
    package_path = staging / "promoted.mrbody"
    receipt_path = staging / "promotion.json"
    evidence_vrm = staging / REVIEW_VRM_NAME
    evidence_bridge = staging / BRIDGE_RESULT_NAME
    evidence_rebuild = staging / REBUILD_RECEIPT_NAME
    evidence_preparation = staging / PREPARATION_NAME
    committed = False
    try:
        shutil.copyfile(eye_vrm_path, evidence_vrm)
        runtime_root = Path(eye_runtime_dir).expanduser().resolve()
        for source, destination in (
            (runtime_root / BRIDGE_RESULT_NAME, evidence_bridge),
            (rebuild_receipt_path, evidence_rebuild),
            (runtime_root / PREPARATION_NAME, evidence_preparation),
        ):
            if not source.is_file():
                raise HighFidelityEyePromotionError(f"eye promotion evidence is missing: {source.name}")
            shutil.copyfile(source, destination)
        _rewrite_package(target, package_path, avatar_vrm=promoted_avatar)
        try:
            validated = validate_package(package_path)
            audit = audit_high_fidelity_package(package_path)
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise HighFidelityEyePromotionError(f"promoted eye package failed strict audit: {exc}") from exc
        if str(validated.manifest["id"]) != body_id:
            raise HighFidelityEyePromotionError("promoted eye package changed canonical body id")
        if audit["components"].get("eyes") != "complete":
            raise HighFidelityEyePromotionError("promoted package did not make eyes complete")
        for component, status in before["components"].items():
            if component != "eyes" and audit["components"].get(component) != status:
                raise HighFidelityEyePromotionError("promoted eye package changed another fidelity component")
        if audit["production_ready"] is not False:
            raise HighFidelityEyePromotionError("eye promotion crossed production authority boundary")
        promoted_package_sha = _sha256_file(package_path)
        promoted_avatar_sha = _sha256_bytes(promoted_avatar)
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policyRevision": POLICY_REVISION,
            "previewJobId": _job(preview_job_id),
            "canonicalBodyId": body_id,
            "promotionBodyRigRevision": promotion_revision,
            "sourceCandidatePackageSha256": source_candidate_sha,
            "destinationSourcePackageSha256": target_sha,
            "eyeRuntimeRebuildReceiptSha256": rebuild_receipt_sha,
            "eyeRuntimeBridgeScriptSha256": embedded["eyeRuntimeBridgeScriptSha256"],
            "reviewedEyeFingerprintSha256": source_fingerprint_sha,
            "rebuiltEyeReviewVrmSha256": embedded["rebuiltEyeReviewVrmSha256"],
            "promotedPackageSha256": promoted_package_sha,
            "promotedAvatarSha256": promoted_avatar_sha,
            "componentsBefore": dict(before["components"]),
            "componentsAfter": dict(after["components"]),
            "hairCompletePreserved": hair_complete,
            "promotionComponent": "eyes",
            "sourceHairRuntimeImported": False,
            "productionActivation": False,
        }
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
        final_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(final_root)
        committed = True
        verified = read_promotion(
            preview_job_id,
            candidate_package_path=candidate_package_path,
            target_package_path=target_package_path,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
            eye_runtime_dir=eye_runtime_dir,
            bridge_script_sha256=bridge_script_sha256,
        )
        return verified
    finally:
        if not committed and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def read_promotion(
    preview_job_id: str,
    *,
    candidate_package_path: str | Path,
    target_package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    eye_runtime_dir: str | Path,
    bridge_script_sha256: str,
) -> dict[str, Any]:
    rebuild, eye_vrm_path, rebuild_receipt_path, rebuild_receipt_sha = _validated_rebuild(
        preview_job_id,
        candidate_package_path=candidate_package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        eye_runtime_dir=eye_runtime_dir,
        bridge_script_sha256=bridge_script_sha256,
    )
    source_candidate_sha = _sha(rebuild["candidatePackageSha256"], label="reviewed candidate package SHA")
    source_fingerprint_sha = _sha(rebuild["sourceFingerprintSha256"], label="reviewed eye fingerprint SHA")
    target = Path(target_package_path).expanduser().resolve()
    target_sha = _sha256_file(target)
    target_avatar, body_id = _package_avatar(target)
    try:
        target_document, _ = _read_glb(target_avatar)
        _target_bodyrig, before, hair_complete = _assert_destination_lineage(
            target_document,
            source_candidate_sha=source_candidate_sha,
            canonical_body_id=body_id,
        )
    except PbrMaterialError as exc:
        raise HighFidelityEyePromotionError(str(exc)) from exc
    final_root = _promotion_root(preview_job_id, target_sha=target_sha, rebuild_sha=rebuild_receipt_sha)
    package_path = final_root / "promoted.mrbody"
    receipt_path = final_root / "promotion.json"
    if not package_path.is_file() or not receipt_path.is_file():
        raise HighFidelityEyePromotionError("eye promotion package/receipt is missing")
    value = _read_json(receipt_path, label="eye promotion receipt")
    required = {
        "format", "version", "policyRevision", "previewJobId", "canonicalBodyId", "promotionBodyRigRevision",
        "sourceCandidatePackageSha256", "destinationSourcePackageSha256", "eyeRuntimeRebuildReceiptSha256",
        "eyeRuntimeBridgeScriptSha256", "reviewedEyeFingerprintSha256", "rebuiltEyeReviewVrmSha256",
        "promotedPackageSha256", "promotedAvatarSha256", "componentsBefore", "componentsAfter",
        "hairCompletePreserved", "promotionComponent", "sourceHairRuntimeImported", "productionActivation",
    }
    if set(value) != required or value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityEyePromotionError("eye promotion receipt fields/format are invalid")
    _revision(value.get("promotionBodyRigRevision"), label="eye promotion BodyRig revision")
    expected = {
        "previewJobId": _job(preview_job_id),
        "canonicalBodyId": body_id,
        "sourceCandidatePackageSha256": source_candidate_sha,
        "destinationSourcePackageSha256": target_sha,
        "eyeRuntimeRebuildReceiptSha256": rebuild_receipt_sha,
        "eyeRuntimeBridgeScriptSha256": _sha(bridge_script_sha256, label="eye bridge script SHA"),
        "reviewedEyeFingerprintSha256": source_fingerprint_sha,
        "rebuiltEyeReviewVrmSha256": rebuild["rebuiltReviewVrmSha256"],
        "promotedPackageSha256": _sha256_file(package_path),
        "hairCompletePreserved": hair_complete,
        "promotionComponent": "eyes",
        "sourceHairRuntimeImported": False,
        "productionActivation": False,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise HighFidelityEyePromotionError(f"eye promotion no longer matches exact authority: {field}")
    promoted_avatar, promoted_body_id = _package_avatar(package_path)
    if promoted_body_id != body_id or value.get("promotedAvatarSha256") != _sha256_bytes(promoted_avatar):
        raise HighFidelityEyePromotionError("promoted eye avatar identity/hash changed")
    try:
        audit = audit_high_fidelity_package(package_path)
        promoted_document, _ = _read_glb(promoted_avatar)
    except (HighFidelityPackageAuditError, PbrMaterialError) as exc:
        raise HighFidelityEyePromotionError(f"promoted eye package revalidation failed: {exc}") from exc
    after = dict(audit["components"])
    if value.get("componentsBefore") != before["components"] or value.get("componentsAfter") != after:
        raise HighFidelityEyePromotionError("eye promotion component state receipt is stale")
    if after.get("eyes") != "complete":
        raise HighFidelityEyePromotionError("promoted package eyes component is not complete")
    for component, status in before["components"].items():
        if component != "eyes" and after.get(component) != status:
            raise HighFidelityEyePromotionError("promoted eye package changed another component on revalidation")
    if audit["production_ready"] is not False:
        raise HighFidelityEyePromotionError("promoted eye package crossed production authority")
    promoted_bodyrig = _bodyrig(promoted_document, label="promoted eye avatar")
    embedded = promoted_bodyrig.get("eyePromotion")
    if not isinstance(embedded, dict) or embedded.get("format") != EMBEDDED_FORMAT or embedded.get("version") != VERSION:
        raise HighFidelityEyePromotionError("embedded eye promotion authority is missing/invalid")
    expected_embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "previewJobId": _job(preview_job_id),
        "promotionBodyRigRevision": value["promotionBodyRigRevision"],
        "canonicalBodyId": body_id,
        "sourceCandidatePackageSha256": source_candidate_sha,
        "destinationSourcePackageSha256": target_sha,
        "eyeRuntimeRebuildReceiptSha256": rebuild_receipt_sha,
        "eyeRuntimeBridgeScriptSha256": expected["eyeRuntimeBridgeScriptSha256"],
        "reviewedEyeFingerprintSha256": source_fingerprint_sha,
        "rebuiltEyeReviewVrmSha256": rebuild["rebuiltReviewVrmSha256"],
        "hairCompletePreserved": hair_complete,
        "component": "eyes",
        "sourceEyeRuntimeImported": True,
        "sourceHairRuntimeImported": False,
        "productionActivation": False,
    }
    if embedded != expected_embedded:
        raise HighFidelityEyePromotionError("embedded eye promotion authority is stale/tampered")
    final_fingerprint = semantic_eye_runtime_fingerprint(promoted_avatar)
    if final_fingerprint.get("fingerprintSha256") != source_fingerprint_sha:
        raise HighFidelityEyePromotionError("promoted package eye-stage fingerprint differs from reviewed authority")
    return {**value, "packagePath": str(package_path), "receiptPath": str(receipt_path)}
