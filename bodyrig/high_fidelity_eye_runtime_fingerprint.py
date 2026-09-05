from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .high_fidelity_eyes_promotion_eligibility import (
    HighFidelityEyesPromotionEligibilityError,
    read_eligibility,
)
from .source_iris_review_runtime import SourceIrisReviewRuntimeError, read_reviewed_runtime
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-eye-runtime-fingerprint"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-eye-runtime-fingerprint-v1"
PAYLOAD_FORMAT = "bodyrig-eye-runtime-semantic-fingerprint"
PAYLOAD_VERSION = 1
ROOT_DIRNAME = ".high-fidelity-eye-runtime-fingerprints"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")

EYE_NODE_NAME = "BodyRigSourceEyeReview"
EYE_MESH_NAME = "BodyRigSourceEyeReviewMesh"
SOURCE_MATERIAL_NAME = "BodyRigSourceEyeSurface"
CORNEA_MATERIAL_NAME = "BodyRigCorneaReview"
SOURCE_IMAGE_NAME = "BodyRigSourceEyeBake"
PRIMITIVE_ROLES = ("left_surface", "left_cornea", "right_surface", "right_cornea")
ATTRIBUTE_ORDER = ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0")
COMPONENT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
EXPECTED_ATTRIBUTE_TYPES = {
    "POSITION": (5126, "VEC3"),
    "NORMAL": (5126, "VEC3"),
    "TEXCOORD_0": (5126, "VEC2"),
    "JOINTS_0": (5123, "VEC4"),
    "WEIGHTS_0": (5126, "VEC4"),
}
EYE_METADATA_FIELDS = {
    "format",
    "version",
    "eyeComponentReceiptSha256",
    "eyeAppearanceReceiptSha256",
    "canonicalEyeBakeSha256",
    "targetModelFamily",
    "leftEyeJointIndex",
    "rightEyeJointIndex",
    "sourceEyeSurfaceApplied",
    "irisIdentityIsolated",
    "irisAppearanceStatus",
    "cornealMaterialStatus",
    "eyelashStatus",
    "skinIndex",
    "physicalFaceCloseupReviewRequired",
    "comparisonOnly",
    "humanReviewRequired",
    "eyeComponentAuthority",
    "productionActivation",
}


class HighFidelityEyeRuntimeFingerprintError(RuntimeError):
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
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} is not a canonical Git SHA")
    return clean


def _job(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityEyeRuntimeFingerprintError("high-fidelity preview job id is not canonical")
    return clean


def _int(value: Any, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} is invalid")
    return value


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} is invalid")
    result = float(value)
    if not (-1.0e308 < result < 1.0e308):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} is non-finite")
    return result


def _canonical_sha(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(raw)


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HighFidelityEyeRuntimeFingerprintError(f"eye runtime glTF {name} array is missing")
    return value


def _indexed(array: list[Any], index: Any, *, label: str) -> dict[str, Any]:
    idx = _int(index, label=f"{label} index")
    if idx >= len(array) or not isinstance(array[idx], dict):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} index is outside the canonical glTF array")
    return array[idx]


def _view_bytes(document: Mapping[str, Any], binary: bytes, index: Any, *, label: str) -> bytes:
    views = _array(document, "bufferViews")
    view = _indexed(views, index, label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} must use the single GLB binary buffer")
    offset = _int(view.get("byteOffset", 0), label=f"{label} bufferView byteOffset")
    length = _int(view.get("byteLength"), label=f"{label} bufferView byteLength", minimum=1)
    end = offset + length
    if end > len(binary):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} bufferView exceeds GLB binary bytes")
    return binary[offset:end]


def _accessor_payload(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
    expected: tuple[int, str] | None = None,
) -> dict[str, Any]:
    accessors = _array(document, "accessors")
    views = _array(document, "bufferViews")
    accessor = _indexed(accessors, index, label=f"{label} accessor")
    if "sparse" in accessor:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} sparse accessors are not canonical")
    if "bufferView" not in accessor:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} accessor has no bufferView")
    component = _int(accessor.get("componentType"), label=f"{label} componentType")
    kind = accessor.get("type")
    if component not in COMPONENT_SIZE or kind not in TYPE_WIDTH:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} accessor type is unsupported")
    if expected is not None and (component, kind) != expected:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} accessor type differs from eye runtime contract")
    count = _int(accessor.get("count"), label=f"{label} count", minimum=1)
    normalized = accessor.get("normalized", False)
    if not isinstance(normalized, bool):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} normalized flag is invalid")

    view = _indexed(views, accessor.get("bufferView"), label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} must use the single GLB binary buffer")
    view_offset = _int(view.get("byteOffset", 0), label=f"{label} view byteOffset")
    view_length = _int(view.get("byteLength"), label=f"{label} view byteLength", minimum=1)
    accessor_offset = _int(accessor.get("byteOffset", 0), label=f"{label} accessor byteOffset")
    element_size = COMPONENT_SIZE[component] * TYPE_WIDTH[kind]
    stride = view.get("byteStride", element_size)
    stride = _int(stride, label=f"{label} byteStride", minimum=1)
    if stride < element_size:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} byteStride is smaller than one element")
    view_end = view_offset + view_length
    if view_end > len(binary):
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} bufferView exceeds GLB binary bytes")
    start = view_offset + accessor_offset
    if start < view_offset:
        raise HighFidelityEyeRuntimeFingerprintError(f"{label} accessor offset underflow")

    tight = bytearray()
    for item in range(count):
        element_start = start + item * stride
        element_end = element_start + element_size
        if element_end > view_end:
            raise HighFidelityEyeRuntimeFingerprintError(f"{label} accessor exceeds its bufferView")
        tight.extend(binary[element_start:element_end])
    raw = bytes(tight)
    return {
        "componentType": component,
        "type": kind,
        "count": count,
        "normalized": normalized,
        "byteLength": len(raw),
        "payloadSha256": _sha256_bytes(raw),
    }


def _sampler_semantics(document: Mapping[str, Any], texture: Mapping[str, Any]) -> dict[str, Any]:
    sampler_index = texture.get("sampler")
    if sampler_index is None:
        return {"present": False, "magFilter": None, "minFilter": None, "wrapS": None, "wrapT": None}
    samplers = _array(document, "samplers")
    sampler = _indexed(samplers, sampler_index, label="source eye sampler")
    result: dict[str, Any] = {"present": True}
    for field in ("magFilter", "minFilter", "wrapS", "wrapT"):
        value = sampler.get(field)
        if value is not None:
            value = _int(value, label=f"source eye sampler {field}", minimum=1)
        result[field] = value
    return result


def _source_material_semantics(document: Mapping[str, Any], binary: bytes, material: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if set(material) != {"name", "doubleSided", "pbrMetallicRoughness"}:
        raise HighFidelityEyeRuntimeFingerprintError("source eye material fields differ from canonical review runtime")
    if material.get("name") != SOURCE_MATERIAL_NAME or material.get("doubleSided") is not False:
        raise HighFidelityEyeRuntimeFingerprintError("source eye surface material identity is invalid")
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, dict) or set(pbr) != {"baseColorTexture", "metallicFactor", "roughnessFactor"}:
        raise HighFidelityEyeRuntimeFingerprintError("source eye PBR fields differ from canonical review runtime")
    texture_info = pbr.get("baseColorTexture")
    if not isinstance(texture_info, dict) or set(texture_info) != {"index"}:
        raise HighFidelityEyeRuntimeFingerprintError("source eye base-color texture reference is invalid")
    textures = _array(document, "textures")
    texture = _indexed(textures, texture_info.get("index"), label="source eye texture")
    if set(texture) != {"sampler", "source"}:
        raise HighFidelityEyeRuntimeFingerprintError("source eye texture fields differ from canonical review runtime")
    images = _array(document, "images")
    image = _indexed(images, texture.get("source"), label="source eye image")
    if set(image) != {"name", "bufferView", "mimeType"}:
        raise HighFidelityEyeRuntimeFingerprintError("source eye image fields differ from canonical review runtime")
    if image.get("name") != SOURCE_IMAGE_NAME or image.get("mimeType") != "image/png":
        raise HighFidelityEyeRuntimeFingerprintError("source eye image identity is invalid")
    named = [item for item in images if isinstance(item, dict) and item.get("name") == SOURCE_IMAGE_NAME]
    if len(named) != 1:
        raise HighFidelityEyeRuntimeFingerprintError("source eye image name is not unique")
    image_bytes = _view_bytes(document, binary, image.get("bufferView"), label="source eye image")
    image_sha = _sha256_bytes(image_bytes)
    semantics = {
        "name": SOURCE_MATERIAL_NAME,
        "doubleSided": False,
        "alphaMode": "OPAQUE",
        "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
        "metallicFactor": _number(pbr.get("metallicFactor"), label="source eye metallicFactor"),
        "roughnessFactor": _number(pbr.get("roughnessFactor"), label="source eye roughnessFactor"),
        "baseColorTexCoord": 0,
        "sourceImageMimeType": "image/png",
        "sourceImageSha256": image_sha,
        "sampler": _sampler_semantics(document, texture),
    }
    if semantics["metallicFactor"] != 0.0 or semantics["roughnessFactor"] != 0.36:
        raise HighFidelityEyeRuntimeFingerprintError("source eye material factors differ from canonical review runtime")
    return semantics, image_sha


def _cornea_material_semantics(material: Mapping[str, Any]) -> dict[str, Any]:
    if set(material) != {"name", "doubleSided", "alphaMode", "pbrMetallicRoughness"}:
        raise HighFidelityEyeRuntimeFingerprintError("cornea material fields differ from canonical review runtime")
    if material.get("name") != CORNEA_MATERIAL_NAME or material.get("doubleSided") is not False or material.get("alphaMode") != "BLEND":
        raise HighFidelityEyeRuntimeFingerprintError("cornea material identity is invalid")
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, dict) or set(pbr) != {"baseColorFactor", "metallicFactor", "roughnessFactor"}:
        raise HighFidelityEyeRuntimeFingerprintError("cornea PBR fields differ from canonical review runtime")
    factor = pbr.get("baseColorFactor")
    if not isinstance(factor, list) or len(factor) != 4:
        raise HighFidelityEyeRuntimeFingerprintError("cornea baseColorFactor is invalid")
    normalized_factor = [_number(value, label="cornea baseColorFactor") for value in factor]
    metallic = _number(pbr.get("metallicFactor"), label="cornea metallicFactor")
    roughness = _number(pbr.get("roughnessFactor"), label="cornea roughnessFactor")
    if normalized_factor != [1.0, 1.0, 1.0, 0.11] or metallic != 0.0 or roughness != 0.04:
        raise HighFidelityEyeRuntimeFingerprintError("cornea material factors differ from canonical review runtime")
    return {
        "name": CORNEA_MATERIAL_NAME,
        "doubleSided": False,
        "alphaMode": "BLEND",
        "baseColorFactor": normalized_factor,
        "metallicFactor": metallic,
        "roughnessFactor": roughness,
    }


def _eye_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    eye = bodyrig.get("eyeReviewRuntime") if isinstance(bodyrig, dict) else None
    if not isinstance(eye, dict) or set(eye) != EYE_METADATA_FIELDS:
        raise HighFidelityEyeRuntimeFingerprintError("embedded eye runtime metadata fields are not canonical")
    if eye.get("format") != "bodyrig-source-eye-review-runtime-metadata" or eye.get("version") != 1:
        raise HighFidelityEyeRuntimeFingerprintError("embedded eye runtime metadata format/version is invalid")
    for field in ("eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256", "canonicalEyeBakeSha256"):
        _sha(eye.get(field), label=f"eye metadata {field}")
    if eye.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise HighFidelityEyeRuntimeFingerprintError("eye metadata target model family is invalid")
    for field in ("leftEyeJointIndex", "rightEyeJointIndex", "skinIndex"):
        _int(eye.get(field), label=f"eye metadata {field}")
    if (
        eye.get("sourceEyeSurfaceApplied") is not True
        or eye.get("irisIdentityIsolated") is not False
        or eye.get("irisAppearanceStatus") != "review-pending"
        or eye.get("cornealMaterialStatus") != "runtime-applied"
        or eye.get("eyelashStatus") != "missing"
        or eye.get("physicalFaceCloseupReviewRequired") is not True
        or eye.get("comparisonOnly") is not True
        or eye.get("humanReviewRequired") is not True
        or eye.get("eyeComponentAuthority") is not False
        or eye.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeFingerprintError("embedded eye runtime metadata crossed its review-only boundary")
    return {field: eye[field] for field in sorted(EYE_METADATA_FIELDS)}


def semantic_eye_runtime_fingerprint(vrm_bytes: bytes) -> dict[str, Any]:
    try:
        document, binary = _read_glb(vrm_bytes)
    except PbrMaterialError as exc:
        raise HighFidelityEyeRuntimeFingerprintError(f"eye runtime GLB is invalid: {exc}") from exc
    nodes = _array(document, "nodes")
    matches = [(index, item) for index, item in enumerate(nodes) if isinstance(item, dict) and item.get("name") == EYE_NODE_NAME]
    if len(matches) != 1:
        raise HighFidelityEyeRuntimeFingerprintError("canonical eye runtime node is missing or ambiguous")
    _node_index, node = matches[0]
    if set(node) != {"name", "mesh", "skin"} or node.get("name") != EYE_NODE_NAME:
        raise HighFidelityEyeRuntimeFingerprintError("canonical eye runtime node fields are invalid")
    _int(node.get("skin"), label="eye runtime skin index")

    meshes = _array(document, "meshes")
    mesh = _indexed(meshes, node.get("mesh"), label="eye runtime mesh")
    if set(mesh) != {"name", "primitives"} or mesh.get("name") != EYE_MESH_NAME:
        raise HighFidelityEyeRuntimeFingerprintError("canonical eye runtime mesh fields are invalid")
    primitives = mesh.get("primitives")
    if not isinstance(primitives, list) or len(primitives) != 4:
        raise HighFidelityEyeRuntimeFingerprintError("canonical eye runtime requires exactly four primitives")

    materials = _array(document, "materials")
    source_named = [item for item in materials if isinstance(item, dict) and item.get("name") == SOURCE_MATERIAL_NAME]
    cornea_named = [item for item in materials if isinstance(item, dict) and item.get("name") == CORNEA_MATERIAL_NAME]
    if len(source_named) != 1 or len(cornea_named) != 1:
        raise HighFidelityEyeRuntimeFingerprintError("canonical source-eye/cornea material names are not unique")
    source_semantics, source_image_sha = _source_material_semantics(document, binary, source_named[0])
    cornea_semantics = _cornea_material_semantics(cornea_named[0])

    primitive_payloads: dict[str, Any] = {}
    for role, primitive in zip(PRIMITIVE_ROLES, primitives):
        if not isinstance(primitive, dict) or set(primitive) != {"attributes", "indices", "material", "mode"}:
            raise HighFidelityEyeRuntimeFingerprintError(f"{role} primitive fields are not canonical")
        if primitive.get("mode") != 4:
            raise HighFidelityEyeRuntimeFingerprintError(f"{role} primitive is not TRIANGLES")
        attributes = primitive.get("attributes")
        if not isinstance(attributes, dict) or set(attributes) != set(ATTRIBUTE_ORDER):
            raise HighFidelityEyeRuntimeFingerprintError(f"{role} primitive attributes are not canonical")
        material = _indexed(materials, primitive.get("material"), label=f"{role} material")
        expected_name = CORNEA_MATERIAL_NAME if role.endswith("cornea") else SOURCE_MATERIAL_NAME
        if material.get("name") != expected_name:
            raise HighFidelityEyeRuntimeFingerprintError(f"{role} primitive uses the wrong material role")
        attribute_payloads = {
            semantic: _accessor_payload(
                document,
                binary,
                attributes[semantic],
                label=f"{role} {semantic}",
                expected=EXPECTED_ATTRIBUTE_TYPES[semantic],
            )
            for semantic in ATTRIBUTE_ORDER
        }
        indices = _accessor_payload(
            document,
            binary,
            primitive.get("indices"),
            label=f"{role} indices",
            expected=(5125, "SCALAR"),
        )
        primitive_payloads[role] = {
            "mode": "TRIANGLES",
            "materialRole": "cornea" if role.endswith("cornea") else "source-surface",
            "attributes": attribute_payloads,
            "indices": indices,
        }

    metadata = _eye_metadata(document)
    if metadata["canonicalEyeBakeSha256"] != source_image_sha:
        raise HighFidelityEyeRuntimeFingerprintError("embedded eye metadata canonical bake SHA differs from rendered source image bytes")
    if metadata["skinIndex"] != node.get("skin"):
        raise HighFidelityEyeRuntimeFingerprintError("embedded eye metadata skin index differs from eye runtime node")

    payload = {
        "format": PAYLOAD_FORMAT,
        "version": PAYLOAD_VERSION,
        "semantics": "index-and-buffer-offset-independent-eye-stage-v1",
        "nodeRole": EYE_NODE_NAME,
        "meshRole": EYE_MESH_NAME,
        "primitiveOrder": list(PRIMITIVE_ROLES),
        "primitives": primitive_payloads,
        "sourceSurfaceMaterial": source_semantics,
        "corneaMaterial": cornea_semantics,
        "eyeMetadata": metadata,
    }
    return {"fingerprintSha256": _canonical_sha(payload), "payload": payload}


def fingerprint_path(preview_job_id: str, *, review_vrm_sha256: str, fingerprint_sha256: str) -> Path:
    job_id = _job(preview_job_id)
    review_sha = _sha(review_vrm_sha256, label="review VRM SHA")
    fingerprint_sha = _sha(fingerprint_sha256, label="eye runtime fingerprint SHA")
    return ui_jobs_dir() / ROOT_DIRNAME / f"{job_id}.{review_sha}.{fingerprint_sha}.json"


def _authorities(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path, Path, dict[str, Any]]:
    try:
        eligibility = read_eligibility(
            preview_job_id,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except HighFidelityEyesPromotionEligibilityError as exc:
        raise HighFidelityEyeRuntimeFingerprintError(f"eyes promotion eligibility authority failed: {exc}") from exc
    if (
        eligibility.get("eyesPromotionEligible") is not True
        or eligibility.get("eyeComponentAuthority") is not False
        or eligibility.get("packageMutationPerformed") is not False
        or eligibility.get("eyesPromoted") is not False
        or eligibility.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeFingerprintError("eyes eligibility crossed its pre-materialization authority boundary")
    eligibility_path_value = Path(str(eligibility.get("eligibilityPath") or "")).expanduser().resolve()
    if not eligibility_path_value.is_file():
        raise HighFidelityEyeRuntimeFingerprintError("eyes eligibility receipt disappeared after validation")

    try:
        reviewed = read_reviewed_runtime(
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except SourceIrisReviewRuntimeError as exc:
        raise HighFidelityEyeRuntimeFingerprintError(f"reviewed iris runtime authority failed: {exc}") from exc
    reviewed_vrm_path = Path(str(reviewed.get("reviewedVrmPath") or "")).expanduser().resolve()
    reviewed_receipt_path = Path(str(reviewed.get("reviewReceiptPath") or "")).expanduser().resolve()
    if not reviewed_vrm_path.is_file() or not reviewed_receipt_path.is_file():
        raise HighFidelityEyeRuntimeFingerprintError("reviewed iris runtime artifacts disappeared after validation")
    review_vrm_sha = _sha(eligibility.get("reviewVrmSha256"), label="eligibility review VRM SHA")
    if reviewed.get("reviewedVrmSha256") != review_vrm_sha or _sha256_file(reviewed_vrm_path) != review_vrm_sha:
        raise HighFidelityEyeRuntimeFingerprintError("fingerprint input is not the exact VRM bytes that received eyes eligibility")
    if eligibility.get("irisReviewedRuntimeReceiptSha256") != _sha256_file(reviewed_receipt_path):
        raise HighFidelityEyeRuntimeFingerprintError("eligibility no longer binds the exact reviewed iris runtime receipt")
    fingerprint = semantic_eye_runtime_fingerprint(reviewed_vrm_path.read_bytes())
    if fingerprint["payload"]["eyeMetadata"]["targetModelFamily"] != eligibility.get("targetModelFamily"):
        raise HighFidelityEyeRuntimeFingerprintError("fingerprinted eye runtime target family differs from eligibility authority")
    if fingerprint["payload"]["eyeMetadata"]["canonicalEyeBakeSha256"] != eligibility.get("canonicalEyeBakeSha256"):
        raise HighFidelityEyeRuntimeFingerprintError("fingerprinted eye source bake differs from eligibility authority")
    if fingerprint["payload"]["eyeMetadata"]["eyeAppearanceReceiptSha256"] != eligibility.get("sourceEyeAppearanceReceiptSha256"):
        raise HighFidelityEyeRuntimeFingerprintError("fingerprinted eye appearance receipt differs from eligibility authority")
    return eligibility, eligibility_path_value, reviewed, reviewed_receipt_path, reviewed_vrm_path, fingerprint


def write_fingerprint(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision, label="fingerprint BodyRig revision")
    eligibility, eligibility_file, reviewed, reviewed_receipt, reviewed_vrm, fingerprint = _authorities(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    review_vrm_sha = _sha(eligibility["reviewVrmSha256"], label="review VRM SHA")
    fingerprint_sha = _sha(fingerprint["fingerprintSha256"], label="eye runtime fingerprint SHA")
    path = fingerprint_path(preview_job_id, review_vrm_sha256=review_vrm_sha, fingerprint_sha256=fingerprint_sha)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "fingerprintBodyrigRevision": revision,
        "eligibilityBodyrigRevision": _revision(eligibility["bodyrigRevision"], label="eligibility BodyRig revision"),
        "reviewedRuntimeBodyrigRevision": _revision(reviewed["bodyrigRevision"], label="reviewed runtime BodyRig revision"),
        "previewJobId": str(eligibility["previewJobId"]),
        "canonicalBodyId": str(eligibility["canonicalBodyId"]),
        "candidatePackageSha256": _sha(eligibility["candidatePackageSha256"], label="candidate package SHA"),
        "eligibilityReceiptSha256": _sha256_file(eligibility_file),
        "irisReviewedRuntimeReceiptSha256": _sha256_file(reviewed_receipt),
        "reviewVrmSha256": review_vrm_sha,
        "reviewVrmBytesVerified": _sha256_file(reviewed_vrm) == review_vrm_sha,
        "fingerprintSha256": fingerprint_sha,
        "fingerprint": fingerprint["payload"],
        "indexIndependent": True,
        "bufferOffsetIndependent": True,
        "eyesPromotionEligibilityVerified": True,
        "eyeComponentAuthority": False,
        "packageMutationPerformed": False,
        "eyesPromoted": False,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
    except FileExistsError as exc:
        raise HighFidelityEyeRuntimeFingerprintError(f"refusing to overwrite existing eye runtime fingerprint: {path}") from exc
    try:
        verified = read_fingerprint(
            preview_job_id,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {**verified, "fingerprintPath": str(path)}


def read_fingerprint(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> dict[str, Any]:
    eligibility, eligibility_file, reviewed, reviewed_receipt, reviewed_vrm, fingerprint = _authorities(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    review_vrm_sha = _sha(eligibility["reviewVrmSha256"], label="review VRM SHA")
    fingerprint_sha = _sha(fingerprint["fingerprintSha256"], label="eye runtime fingerprint SHA")
    path = fingerprint_path(preview_job_id, review_vrm_sha256=review_vrm_sha, fingerprint_sha256=fingerprint_sha)
    if not path.is_file():
        raise HighFidelityEyeRuntimeFingerprintError(f"eye runtime fingerprint receipt is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityEyeRuntimeFingerprintError("eye runtime fingerprint receipt is unreadable") from exc
    required = {
        "format", "version", "policyRevision", "fingerprintBodyrigRevision", "eligibilityBodyrigRevision",
        "reviewedRuntimeBodyrigRevision", "previewJobId", "canonicalBodyId", "candidatePackageSha256",
        "eligibilityReceiptSha256", "irisReviewedRuntimeReceiptSha256", "reviewVrmSha256",
        "reviewVrmBytesVerified", "fingerprintSha256", "fingerprint", "indexIndependent",
        "bufferOffsetIndependent", "eyesPromotionEligibilityVerified", "eyeComponentAuthority",
        "packageMutationPerformed", "eyesPromoted", "humanReviewRequired", "productionActivation",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise HighFidelityEyeRuntimeFingerprintError("eye runtime fingerprint receipt fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityEyeRuntimeFingerprintError("eye runtime fingerprint format/version/policy mismatch")
    _revision(value.get("fingerprintBodyrigRevision"), label="fingerprint BodyRig revision")
    exact = {
        "eligibilityBodyrigRevision": eligibility["bodyrigRevision"],
        "reviewedRuntimeBodyrigRevision": reviewed["bodyrigRevision"],
        "previewJobId": eligibility["previewJobId"],
        "canonicalBodyId": eligibility["canonicalBodyId"],
        "candidatePackageSha256": eligibility["candidatePackageSha256"],
        "eligibilityReceiptSha256": _sha256_file(eligibility_file),
        "irisReviewedRuntimeReceiptSha256": _sha256_file(reviewed_receipt),
        "reviewVrmSha256": review_vrm_sha,
        "fingerprintSha256": fingerprint_sha,
    }
    for field, expected in exact.items():
        if str(value.get(field) or "") != str(expected or ""):
            raise HighFidelityEyeRuntimeFingerprintError(f"eye runtime fingerprint no longer matches exact authority: {field}")
    if value.get("fingerprint") != fingerprint["payload"] or _canonical_sha(value["fingerprint"]) != fingerprint_sha:
        raise HighFidelityEyeRuntimeFingerprintError("eye runtime semantic fingerprint payload no longer matches reviewed VRM bytes")
    if _sha256_file(reviewed_vrm) != review_vrm_sha:
        raise HighFidelityEyeRuntimeFingerprintError("reviewed VRM bytes changed after fingerprint authority validation")
    if (
        value.get("reviewVrmBytesVerified") is not True
        or value.get("indexIndependent") is not True
        or value.get("bufferOffsetIndependent") is not True
        or value.get("eyesPromotionEligibilityVerified") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("eyesPromoted") is not False
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeFingerprintError("eye runtime fingerprint crossed its non-materializing authority boundary")
    return {**value, "fingerprintPath": str(path)}
