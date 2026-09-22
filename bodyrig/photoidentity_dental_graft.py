from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .fine_identity_application import (
    FineIdentityApplicationError,
    validate_requirement as validate_fine_identity_requirement,
)
from .photoidentity_dental_reconstruction import (
    DENTAL_MATERIAL,
    MOUTH_MATERIAL,
    REQUIRED_ROLES,
    RESULT_FIELDS,
    RESULT_FORMAT,
    RESULT_VERSION,
    PhotoIdentityDentalReconstructionError,
    validate_dental_vrm,
)

GRAFT_NODE_NAME = "BodyRigSourceDentalIdentityReview"
GRAFT_MESH_NAME = "BodyRigSourceDentalIdentityReviewMesh"
GRAFT_MOUTH_MATERIAL = "BodyRigSourceMouthInteriorReview"
GRAFT_DENTAL_MATERIAL = "BodyRigSourceDentalSurfaceReview"

_COMPONENT_BYTES = {
    5120: 1,
    5121: 1,
    5122: 2,
    5123: 2,
    5125: 4,
    5126: 4,
}
_TYPE_WIDTH = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class PhotoIdentityDentalGraftError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityDentalGraftError(f"required dental evidence is missing or symlinked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityDentalGraftError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityDentalGraftError(f"{label} must be a JSON object")
    return value


def load_dental_candidate(
    *,
    vrm_path: str | Path,
    result_path: str | Path,
    fine_identity_requirement: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        requirement = validate_fine_identity_requirement(fine_identity_requirement)
    except FineIdentityApplicationError as exc:
        raise PhotoIdentityDentalGraftError(f"photoidentical fine-identity requirement is invalid: {exc}") from exc

    vrm_file = Path(vrm_path).expanduser().resolve()
    result_file = Path(result_path).expanduser().resolve()
    vrm_sha = _sha256_file(vrm_file)
    result_sha = _sha256_file(result_file)
    result = _read_json(result_file, label="Dental reconstruction result")
    if set(result) != RESULT_FIELDS:
        raise PhotoIdentityDentalGraftError("dental reconstruction result fields must match v1 exactly")
    if result.get("format") != RESULT_FORMAT or result.get("version") != RESULT_VERSION:
        raise PhotoIdentityDentalGraftError("dental reconstruction result format/version mismatch")
    expected_boundary = {
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
        "generative_identity_synthesis": False,
        "mouth_interior_source_derived": True,
        "upper_teeth_source_derived": True,
        "lower_teeth_source_derived": True,
        "appearance_source_derived": True,
        "human_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
    }
    for field, expected in expected_boundary.items():
        if result.get(field) is not expected:
            raise PhotoIdentityDentalGraftError(f"dental reconstruction authority mismatch: {field}")
    if str(result.get("bodyrig_revision") or "").lower() != str(requirement["bodyrigRevision"]):
        raise PhotoIdentityDentalGraftError("dental reconstruction BodyRig revision does not match fine-identity authority")
    if str(result.get("fine_identity_attestation_sha256") or "").lower() != str(requirement["fineIdentityAttestationSha256"]):
        raise PhotoIdentityDentalGraftError("dental reconstruction attestation does not match fine-identity authority")
    if str(result.get("dental_vrm_sha256") or "").lower() != vrm_sha:
        raise PhotoIdentityDentalGraftError("dental reconstruction result no longer binds exact dental VRM bytes")
    references = result.get("source_references")
    if (
        not isinstance(references, list)
        or len(references) < 2
        or any(not isinstance(item, str) or not item.strip() for item in references)
        or len(set(references)) != len(references)
    ):
        raise PhotoIdentityDentalGraftError("dental reconstruction source references are invalid")

    vrm_bytes = vrm_file.read_bytes()
    try:
        detail = validate_dental_vrm(vrm_bytes)
        document, _binary = _read_glb(vrm_bytes)
    except (PhotoIdentityDentalReconstructionError, PbrMaterialError) as exc:
        raise PhotoIdentityDentalGraftError(str(exc)) from exc

    node = document["nodes"][detail["node_index"]]
    if any(key in node for key in ("matrix", "rotation", "scale")):
        raise PhotoIdentityDentalGraftError("dental candidate node must be authored in canonical untransformed BodyRig space")
    translation = node.get("translation", [0.0, 0.0, 0.0])
    if translation != [0.0, 0.0, 0.0]:
        raise PhotoIdentityDentalGraftError("dental candidate node translation must be canonical zero")
    metadata = detail["metadata"]
    metadata_expected = {
        "adapter": result.get("adapter"),
        "adapterRevision": result.get("adapter_revision"),
        "bodyrigRevision": requirement["bodyrigRevision"],
        "performerId": result.get("performer_id"),
        "fineIdentityAttestationSha256": requirement["fineIdentityAttestationSha256"],
    }
    for field, expected in metadata_expected.items():
        if metadata.get(field) != expected:
            raise PhotoIdentityDentalGraftError(f"dental candidate metadata mismatch: {field}")

    return {
        "vrm_bytes": vrm_bytes,
        "vrm_sha256": vrm_sha,
        "result_sha256": result_sha,
        "result": result,
        "detail": detail,
        "source_references": list(references),
        "fine_identity_attestation_sha256": requirement["fineIdentityAttestationSha256"],
        "fine_identity_authority_sha256": requirement["fineIdentityAuthoritySha256"],
        "fine_identity_bodyrig_revision": requirement["bodyrigRevision"],
    }


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise PhotoIdentityDentalGraftError(f"VRM glTF {name} array is missing")
    return value


def _copy_accessor(
    *,
    source_document: Mapping[str, Any],
    source_binary: bytes,
    source_index: int,
    destination_document: dict[str, Any],
    destination_binary: bytearray,
    target: int,
) -> int:
    source_accessors = _array(source_document, "accessors")
    source_views = _array(source_document, "bufferViews")
    if isinstance(source_index, bool) or not isinstance(source_index, int) or not 0 <= source_index < len(source_accessors):
        raise PhotoIdentityDentalGraftError("dental accessor index is invalid")
    accessor = source_accessors[source_index]
    if not isinstance(accessor, Mapping) or "sparse" in accessor:
        raise PhotoIdentityDentalGraftError("dental accessor must be dense")
    view_index = accessor.get("bufferView")
    if isinstance(view_index, bool) or not isinstance(view_index, int) or not 0 <= view_index < len(source_views):
        raise PhotoIdentityDentalGraftError("dental accessor bufferView is invalid")
    view = source_views[view_index]
    if not isinstance(view, Mapping) or view.get("buffer", 0) != 0:
        raise PhotoIdentityDentalGraftError("dental accessor must use embedded buffer 0")

    component = accessor.get("componentType")
    count = accessor.get("count")
    kind = accessor.get("type")
    if component not in _COMPONENT_BYTES or kind not in _TYPE_WIDTH:
        raise PhotoIdentityDentalGraftError("dental accessor component/type is unsupported")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotoIdentityDentalGraftError("dental accessor count is invalid")
    item_bytes = _COMPONENT_BYTES[component] * _TYPE_WIDTH[kind]
    stride = view.get("byteStride")
    if stride is not None and stride != item_bytes:
        raise PhotoIdentityDentalGraftError("interleaved dental accessors are not accepted by the graft boundary")
    view_offset = view.get("byteOffset", 0)
    view_length = view.get("byteLength")
    accessor_offset = accessor.get("byteOffset", 0)
    if (
        isinstance(view_offset, bool)
        or not isinstance(view_offset, int)
        or view_offset < 0
        or isinstance(view_length, bool)
        or not isinstance(view_length, int)
        or view_length < 0
        or isinstance(accessor_offset, bool)
        or not isinstance(accessor_offset, int)
        or accessor_offset < 0
    ):
        raise PhotoIdentityDentalGraftError("dental accessor byte bounds are invalid")
    byte_length = count * item_bytes
    start = view_offset + accessor_offset
    end = start + byte_length
    if end > view_offset + view_length or end > len(source_binary):
        raise PhotoIdentityDentalGraftError("dental accessor exceeds its embedded bufferView")
    raw = source_binary[start:end]

    destination_views = _array(destination_document, "bufferViews")
    destination_accessors = _array(destination_document, "accessors")
    while len(destination_binary) % 4:
        destination_binary.append(0)
    offset = len(destination_binary)
    destination_binary.extend(raw)
    destination_views.append(
        {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(raw),
            "target": target,
        }
    )
    copied: dict[str, Any] = {
        "bufferView": len(destination_views) - 1,
        "componentType": component,
        "count": count,
        "type": kind,
    }
    for key in ("normalized", "min", "max"):
        if key in accessor:
            copied[key] = copy.deepcopy(accessor[key])
    destination_accessors.append(copied)
    return len(destination_accessors) - 1


def _append_accessor(
    *,
    document: dict[str, Any],
    binary: bytearray,
    raw: bytes,
    component_type: int,
    count: int,
    accessor_type: str,
    target: int,
) -> int:
    views = _array(document, "bufferViews")
    accessors = _array(document, "accessors")
    while len(binary) % 4:
        binary.append(0)
    offset = len(binary)
    binary.extend(raw)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": component_type,
            "count": count,
            "type": accessor_type,
        }
    )
    return len(accessors) - 1


def _copy_image(
    *,
    source_document: Mapping[str, Any],
    source_binary: bytes,
    image_index: int,
    destination_document: dict[str, Any],
    destination_binary: bytearray,
    cache: dict[int, int],
) -> int:
    if image_index in cache:
        return cache[image_index]
    images = _array(source_document, "images")
    views = _array(source_document, "bufferViews")
    if isinstance(image_index, bool) or not isinstance(image_index, int) or not 0 <= image_index < len(images):
        raise PhotoIdentityDentalGraftError("dental material image index is invalid")
    image = images[image_index]
    if not isinstance(image, Mapping) or "uri" in image:
        raise PhotoIdentityDentalGraftError("dental graft accepts embedded material images only")
    view_index = image.get("bufferView")
    if isinstance(view_index, bool) or not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise PhotoIdentityDentalGraftError("dental material image bufferView is invalid")
    view = views[view_index]
    if not isinstance(view, Mapping) or view.get("buffer", 0) != 0:
        raise PhotoIdentityDentalGraftError("dental material image must use buffer 0")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length < 1
        or offset + length > len(source_binary)
    ):
        raise PhotoIdentityDentalGraftError("dental material image bounds are invalid")
    raw = source_binary[offset : offset + length]
    destination_views = _array(destination_document, "bufferViews")
    destination_images = destination_document.setdefault("images", [])
    if not isinstance(destination_images, list):
        raise PhotoIdentityDentalGraftError("destination images array is invalid")
    while len(destination_binary) % 4:
        destination_binary.append(0)
    new_offset = len(destination_binary)
    destination_binary.extend(raw)
    destination_views.append(
        {
            "buffer": 0,
            "byteOffset": new_offset,
            "byteLength": len(raw),
        }
    )
    copied = copy.deepcopy(dict(image))
    copied["bufferView"] = len(destination_views) - 1
    copied["name"] = f"BodyRigSourceDentalImage{image_index}"
    destination_images.append(copied)
    cache[image_index] = len(destination_images) - 1
    return cache[image_index]


def _copy_material(
    *,
    source_document: Mapping[str, Any],
    source_binary: bytes,
    material_index: int,
    destination_document: dict[str, Any],
    destination_binary: bytearray,
    material_name: str,
    texture_cache: dict[int, int],
    image_cache: dict[int, int],
    sampler_cache: dict[int, int],
) -> int:
    materials = _array(source_document, "materials")
    if isinstance(material_index, bool) or not isinstance(material_index, int) or not 0 <= material_index < len(materials):
        raise PhotoIdentityDentalGraftError("dental material index is invalid")
    source_material = materials[material_index]
    if not isinstance(source_material, Mapping) or "extensions" in source_material:
        raise PhotoIdentityDentalGraftError("dental graft does not accept material extensions with unresolved texture authority")
    material = copy.deepcopy(dict(source_material))

    destination_textures = destination_document.setdefault("textures", [])
    destination_samplers = destination_document.setdefault("samplers", [])
    if not isinstance(destination_textures, list) or not isinstance(destination_samplers, list):
        raise PhotoIdentityDentalGraftError("destination texture/sampler arrays are invalid")
    source_textures = _array(source_document, "textures")
    source_samplers = source_document.get("samplers", [])
    if not isinstance(source_samplers, list):
        raise PhotoIdentityDentalGraftError("source samplers array is invalid")

    def copy_sampler(index: int) -> int:
        if index in sampler_cache:
            return sampler_cache[index]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(source_samplers):
            raise PhotoIdentityDentalGraftError("dental texture sampler index is invalid")
        sampler = source_samplers[index]
        if not isinstance(sampler, Mapping):
            raise PhotoIdentityDentalGraftError("dental texture sampler is invalid")
        destination_samplers.append(copy.deepcopy(dict(sampler)))
        sampler_cache[index] = len(destination_samplers) - 1
        return sampler_cache[index]

    def copy_texture(index: int) -> int:
        if index in texture_cache:
            return texture_cache[index]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(source_textures):
            raise PhotoIdentityDentalGraftError("dental texture index is invalid")
        texture = source_textures[index]
        if not isinstance(texture, Mapping) or "extensions" in texture:
            raise PhotoIdentityDentalGraftError("dental texture extensions are not supported at the graft boundary")
        source_image = texture.get("source")
        if isinstance(source_image, bool) or not isinstance(source_image, int):
            raise PhotoIdentityDentalGraftError("dental texture source image is invalid")
        copied = copy.deepcopy(dict(texture))
        copied["source"] = _copy_image(
            source_document=source_document,
            source_binary=source_binary,
            image_index=source_image,
            destination_document=destination_document,
            destination_binary=destination_binary,
            cache=image_cache,
        )
        if "sampler" in copied:
            copied["sampler"] = copy_sampler(copied["sampler"])
        destination_textures.append(copied)
        texture_cache[index] = len(destination_textures) - 1
        return texture_cache[index]

    slots: list[dict[str, Any]] = []
    pbr = material.get("pbrMetallicRoughness")
    if isinstance(pbr, dict):
        for field in ("baseColorTexture", "metallicRoughnessTexture"):
            info = pbr.get(field)
            if isinstance(info, dict):
                slots.append(info)
    for field in ("normalTexture", "occlusionTexture", "emissiveTexture"):
        info = material.get(field)
        if isinstance(info, dict):
            slots.append(info)
    for info in slots:
        index = info.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise PhotoIdentityDentalGraftError("dental material texture info is invalid")
        info["index"] = copy_texture(index)

    material["name"] = material_name
    destination_materials = _array(destination_document, "materials")
    destination_materials.append(material)
    return len(destination_materials) - 1


def graft_dental_candidate(
    *,
    destination_vrm: bytes,
    candidate_vrm: bytes,
    head_skin_joint: int,
    jaw_skin_joint: int,
) -> bytes:
    if (
        isinstance(head_skin_joint, bool)
        or not isinstance(head_skin_joint, int)
        or head_skin_joint < 0
        or isinstance(jaw_skin_joint, bool)
        or not isinstance(jaw_skin_joint, int)
        or jaw_skin_joint < 0
        or head_skin_joint > 65535
        or jaw_skin_joint > 65535
    ):
        raise PhotoIdentityDentalGraftError("destination head/jaw skin joint indices are invalid")
    try:
        source_document, source_binary = _read_glb(candidate_vrm)
        destination_document, destination_binary_raw = _read_glb(destination_vrm)
        detail = validate_dental_vrm(candidate_vrm)
    except (PbrMaterialError, PhotoIdentityDentalReconstructionError) as exc:
        raise PhotoIdentityDentalGraftError(str(exc)) from exc

    destination_binary = bytearray(destination_binary_raw)
    destination_nodes = _array(destination_document, "nodes")
    destination_meshes = _array(destination_document, "meshes")
    destination_scenes = _array(destination_document, "scenes")
    destination_buffers = _array(destination_document, "buffers")
    destination_materials = _array(destination_document, "materials")
    if (
        len(destination_buffers) != 1
        or not destination_scenes
        or not isinstance(destination_scenes[0], dict)
        or not isinstance(destination_scenes[0].get("nodes"), list)
    ):
        raise PhotoIdentityDentalGraftError("destination VRM scene/buffer contract is invalid")
    for name in (GRAFT_NODE_NAME, GRAFT_MESH_NAME):
        arrays = destination_nodes if name == GRAFT_NODE_NAME else destination_meshes
        if any(isinstance(item, Mapping) and item.get("name") == name for item in arrays):
            raise PhotoIdentityDentalGraftError("source-derived dental graft already exists")
    existing_material_names = {
        str(item.get("name") or "")
        for item in destination_materials
        if isinstance(item, Mapping)
    }
    if GRAFT_MOUTH_MATERIAL in existing_material_names or GRAFT_DENTAL_MATERIAL in existing_material_names:
        raise PhotoIdentityDentalGraftError("source-derived dental graft materials already exist")

    texture_cache: dict[int, int] = {}
    image_cache: dict[int, int] = {}
    sampler_cache: dict[int, int] = {}
    mouth_material = _copy_material(
        source_document=source_document,
        source_binary=source_binary,
        material_index=detail["mouth_material_index"],
        destination_document=destination_document,
        destination_binary=destination_binary,
        material_name=GRAFT_MOUTH_MATERIAL,
        texture_cache=texture_cache,
        image_cache=image_cache,
        sampler_cache=sampler_cache,
    )
    dental_material = _copy_material(
        source_document=source_document,
        source_binary=source_binary,
        material_index=detail["dental_material_index"],
        destination_document=destination_document,
        destination_binary=destination_binary,
        material_name=GRAFT_DENTAL_MATERIAL,
        texture_cache=texture_cache,
        image_cache=image_cache,
        sampler_cache=sampler_cache,
    )

    source_meshes = _array(source_document, "meshes")
    source_mesh = source_meshes[detail["mesh_index"]]
    primitives = source_mesh.get("primitives") if isinstance(source_mesh, Mapping) else None
    if not isinstance(primitives, list):
        raise PhotoIdentityDentalGraftError("dental source mesh primitives are invalid")

    graft_primitives: list[dict[str, Any]] = []
    for primitive in primitives:
        if not isinstance(primitive, Mapping):
            raise PhotoIdentityDentalGraftError("dental source primitive is invalid")
        extras = primitive.get("extras")
        role = extras.get("bodyrigDentalRole") if isinstance(extras, Mapping) else None
        if role not in REQUIRED_ROLES:
            raise PhotoIdentityDentalGraftError("dental source primitive role is invalid")
        attrs = primitive.get("attributes")
        if not isinstance(attrs, Mapping):
            raise PhotoIdentityDentalGraftError("dental source primitive attributes are invalid")
        position = attrs.get("POSITION")
        normal = attrs.get("NORMAL")
        texcoord = attrs.get("TEXCOORD_0")
        indices = primitive.get("indices")
        copied_attrs = {
            "POSITION": _copy_accessor(
                source_document=source_document,
                source_binary=source_binary,
                source_index=position,
                destination_document=destination_document,
                destination_binary=destination_binary,
                target=34962,
            ),
            "NORMAL": _copy_accessor(
                source_document=source_document,
                source_binary=source_binary,
                source_index=normal,
                destination_document=destination_document,
                destination_binary=destination_binary,
                target=34962,
            ),
            "TEXCOORD_0": _copy_accessor(
                source_document=source_document,
                source_binary=source_binary,
                source_index=texcoord,
                destination_document=destination_document,
                destination_binary=destination_binary,
                target=34962,
            ),
        }
        position_accessor = _array(destination_document, "accessors")[copied_attrs["POSITION"]]
        vertex_count = position_accessor.get("count") if isinstance(position_accessor, Mapping) else None
        if isinstance(vertex_count, bool) or not isinstance(vertex_count, int) or vertex_count < 1:
            raise PhotoIdentityDentalGraftError("dental graft vertex count is invalid")
        joint = head_skin_joint if role == "upper_teeth" else jaw_skin_joint
        joint_raw = b"".join(struct.pack("<4H", joint, 0, 0, 0) for _ in range(vertex_count))
        weight_raw = b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(vertex_count))
        copied_attrs["JOINTS_0"] = _append_accessor(
            document=destination_document,
            binary=destination_binary,
            raw=joint_raw,
            component_type=5123,
            count=vertex_count,
            accessor_type="VEC4",
            target=34962,
        )
        copied_attrs["WEIGHTS_0"] = _append_accessor(
            document=destination_document,
            binary=destination_binary,
            raw=weight_raw,
            component_type=5126,
            count=vertex_count,
            accessor_type="VEC4",
            target=34962,
        )
        copied_indices = _copy_accessor(
            source_document=source_document,
            source_binary=source_binary,
            source_index=indices,
            destination_document=destination_document,
            destination_binary=destination_binary,
            target=34963,
        )
        graft_primitives.append(
            {
                "attributes": copied_attrs,
                "indices": copied_indices,
                "material": mouth_material if role == "mouth_interior" else dental_material,
                "mode": 4,
                "extras": {
                    "bodyrigFaceSecondaryRole": role,
                    "bodyrigDentalRole": role,
                    "bodyrigDentalReboundJoint": "smplx_head" if role == "upper_teeth" else "smplx_jaw",
                    "sourceDerivedDentalIdentity": True,
                },
            }
        )

    if {item["extras"]["bodyrigDentalRole"] for item in graft_primitives} != set(REQUIRED_ROLES):
        raise PhotoIdentityDentalGraftError("dental graft did not preserve the canonical role set")
    destination_meshes.append({"name": GRAFT_MESH_NAME, "primitives": graft_primitives})
    destination_nodes.append({"name": GRAFT_NODE_NAME, "mesh": len(destination_meshes) - 1, "skin": 0})
    destination_scenes[0]["nodes"].append(len(destination_nodes) - 1)
    destination_buffers[0]["byteLength"] = len(destination_binary)
    return _write_glb(destination_document, bytes(destination_binary))
