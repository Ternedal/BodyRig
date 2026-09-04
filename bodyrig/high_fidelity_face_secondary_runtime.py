from __future__ import annotations

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.avatar_fidelity_components import FidelityComponentError, validate_receipt
from .bridges.face_secondary_fidelity import FaceSecondaryFidelityError, validate_face_secondary_receipt
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-high-fidelity-face-secondary-runtime"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-face-secondary-runtime-v1"
REVIEW_METADATA_FORMAT = "bodyrig-face-secondary-review-runtime"
REVIEW_VRM_NAME = "face-secondary-review.vrm"
RECEIPT_NAME = "face-secondary-review-runtime.json"
EYE_PROMOTION_FORMAT = "bodyrig-eye-promotion"
APPEARANCE_METHOD = "canonical-smplx-anatomy-normal-bake-v2"
JOINT_NAMES = ("smplx_head", "smplx_jaw", "smplx_left_eye", "smplx_right_eye")
MATERIAL_NAMES = {
    "mouth": "BodyRigMouthInteriorReview",
    "teeth": "BodyRigTeethReview",
    "lashes": "BodyRigEyelashesReview",
}
MESH_NAME = "BodyRigFaceSecondaryReviewMesh"
NODE_NAME = "BodyRigFaceSecondaryReview"


class HighFidelityFaceSecondaryRuntimeError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _bodyrig(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HighFidelityFaceSecondaryRuntimeError("BodyRig metadata is missing")
    return bodyrig


def _package_avatar(path: Path) -> tuple[bytes, str, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary source package is invalid") from exc
    return avatar, str(validated.manifest["id"]), _sha256_file(path)


def _validate_source(document: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bodyrig = _bodyrig(document)
    try:
        top = validate_receipt(bodyrig.get("fidelityComponents", {}))
        face = validate_face_secondary_receipt(bodyrig.get("faceSecondaryFidelity", {}))
    except (FidelityComponentError, FaceSecondaryFidelityError) as exc:
        raise HighFidelityFaceSecondaryRuntimeError(str(exc)) from exc
    if top["components"].get("body_anatomy") != "complete" or top["components"].get("eyes") != "complete":
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary runtime requires body_anatomy=complete and eyes=complete")
    if face["faceSecondaryReady"] is True or top["components"].get("face_secondary") == "complete":
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary is already complete")
    eye = bodyrig.get("eyePromotion")
    if not isinstance(eye, dict) or eye.get("format") != EYE_PROMOTION_FORMAT or eye.get("version") != 1:
        raise HighFidelityFaceSecondaryRuntimeError("canonical embedded eye promotion authority is required")
    if eye.get("sourceHairRuntimeImported") is not False or eye.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryRuntimeError("eye promotion crossed the review-only source boundary")
    appearance = bodyrig.get("appearanceTransfer")
    if not isinstance(appearance, dict) or appearance.get("method") != APPEARANCE_METHOD:
        raise HighFidelityFaceSecondaryRuntimeError("canonical source-derived anatomy appearance authority is required")
    if (
        appearance.get("canonicalDonorAtlas") is not True
        or appearance.get("sourceDerivedPbrApplied") is not True
        or appearance.get("boundedBaseColorRefinementApplied") is not True
        or appearance.get("generativeAppearanceSynthesis") is not False
        or appearance.get("geometryModified") is not False
    ):
        raise HighFidelityFaceSecondaryRuntimeError("source-derived face appearance authority is invalid")
    if "faceSecondaryReviewRuntime" in bodyrig:
        raise HighFidelityFaceSecondaryRuntimeError("source package already contains face-secondary review runtime metadata")
    return bodyrig, top, face


def _node_parent_map(document: Mapping[str, Any]) -> dict[int, int]:
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise HighFidelityFaceSecondaryRuntimeError("VRM nodes are missing")
    parents: dict[int, int] = {}
    for parent, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        children = node.get("children", [])
        if not isinstance(children, list):
            raise HighFidelityFaceSecondaryRuntimeError("VRM node children are invalid")
        for child in children:
            if isinstance(child, bool) or not isinstance(child, int) or child < 0 or child >= len(nodes) or child in parents:
                raise HighFidelityFaceSecondaryRuntimeError("VRM skeleton parent graph is invalid")
            parents[child] = parent
    return parents


def _joint_world(document: Mapping[str, Any], name: str) -> tuple[int, tuple[float, float, float]]:
    nodes = document.get("nodes")
    skins = document.get("skins")
    if not isinstance(nodes, list) or not isinstance(skins, list) or not skins or not isinstance(skins[0], dict):
        raise HighFidelityFaceSecondaryRuntimeError("canonical skin 0 is missing")
    matches = [index for index, node in enumerate(nodes) if isinstance(node, dict) and node.get("name") == name]
    if len(matches) != 1:
        raise HighFidelityFaceSecondaryRuntimeError(f"canonical joint {name} is missing or ambiguous")
    node_index = matches[0]
    joints = skins[0].get("joints")
    if not isinstance(joints, list) or node_index not in joints:
        raise HighFidelityFaceSecondaryRuntimeError(f"canonical joint {name} is not in skin 0")
    skin_joint = joints.index(node_index)
    parents = _node_parent_map(document)
    chain: list[int] = []
    cursor = node_index
    while True:
        chain.append(cursor)
        if cursor not in parents:
            break
        cursor = parents[cursor]
        if len(chain) > len(nodes):
            raise HighFidelityFaceSecondaryRuntimeError("VRM skeleton contains a cycle")
    x = y = z = 0.0
    for index in reversed(chain):
        node = nodes[index]
        if not isinstance(node, dict):
            raise HighFidelityFaceSecondaryRuntimeError("VRM skeleton node is invalid")
        if any(key in node for key in ("matrix", "rotation", "scale")):
            raise HighFidelityFaceSecondaryRuntimeError("face-secondary v1 requires translation-only SMPL-X rest joints")
        translation = node.get("translation", [0.0, 0.0, 0.0])
        if not isinstance(translation, list) or len(translation) != 3:
            raise HighFidelityFaceSecondaryRuntimeError("VRM joint translation is invalid")
        values: list[float] = []
        for value in translation:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise HighFidelityFaceSecondaryRuntimeError("VRM joint translation is non-finite")
            values.append(float(value))
        x += values[0]
        y += values[1]
        z += values[2]
    return skin_joint, (x, y, z)


def _box(center: tuple[float, float, float], size: tuple[float, float, float], joint: int) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]:
    cx, cy, cz = center
    sx, sy, sz = (value * 0.5 for value in size)
    corners = [
        (cx - sx, cy - sy, cz - sz), (cx + sx, cy - sy, cz - sz),
        (cx + sx, cy + sy, cz - sz), (cx - sx, cy + sy, cz - sz),
        (cx - sx, cy - sy, cz + sz), (cx + sx, cy - sy, cz + sz),
        (cx + sx, cy + sy, cz + sz), (cx - sx, cy + sy, cz + sz),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    normals: list[tuple[float, float, float]] = []
    for x, y, z in corners:
        dx, dy, dz = x - cx, y - cy, z - cz
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        normals.append((dx / length, dy / length, dz / length))
    return corners, normals, faces, joint


def _lash(center: tuple[float, float, float], interocular: float, joint: int) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]:
    cx, cy, cz = center
    half = interocular * 0.19
    rise = interocular * 0.035
    thickness = interocular * 0.012
    vertices: list[tuple[float, float, float]] = []
    segments = 8
    for row in (0, 1):
        for index in range(segments + 1):
            t = index / segments
            x = cx - half + 2.0 * half * t
            curve = 1.0 - ((t - 0.5) / 0.5) ** 2
            y = cy + interocular * 0.105 + rise * curve + (thickness if row else 0.0)
            z = cz + interocular * 0.105
            vertices.append((x, y, z))
    faces: list[tuple[int, int, int]] = []
    stride = segments + 1
    for index in range(segments):
        a, b = index, index + 1
        c, d = stride + index, stride + index + 1
        faces.extend(((a, c, b), (b, c, d)))
    normals = [(0.0, 0.0, 1.0)] * len(vertices)
    return vertices, normals, faces, joint


def _append_geometry(document: dict[str, Any], binary_raw: bytes, primitives_source: list[tuple[str, list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]]) -> bytes:
    arrays = {key: document.get(key) for key in ("bufferViews", "accessors", "materials", "meshes", "nodes", "scenes", "buffers")}
    if any(not isinstance(value, list) for value in arrays.values()):
        raise HighFidelityFaceSecondaryRuntimeError("VRM glTF arrays are incomplete")
    views, accessors = arrays["bufferViews"], arrays["accessors"]
    materials, meshes, nodes = arrays["materials"], arrays["meshes"], arrays["nodes"]
    scenes, buffers = arrays["scenes"], arrays["buffers"]
    assert isinstance(views, list) and isinstance(accessors, list) and isinstance(materials, list)
    assert isinstance(meshes, list) and isinstance(nodes, list) and isinstance(scenes, list) and isinstance(buffers, list)
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list) or len(buffers) != 1:
        raise HighFidelityFaceSecondaryRuntimeError("VRM scene/buffer contract is invalid")
    existing_names = {str(item.get("name") or "") for item in materials if isinstance(item, dict)}
    if any(name in existing_names for name in MATERIAL_NAMES.values()):
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary review materials already exist")
    if any(isinstance(item, dict) and item.get("name") == NODE_NAME for item in nodes):
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary review node already exists")

    materials.extend([
        {"name": MATERIAL_NAMES["mouth"], "doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [0.20, 0.035, 0.045, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.68}},
        {"name": MATERIAL_NAMES["teeth"], "doubleSided": False, "pbrMetallicRoughness": {"baseColorFactor": [0.93, 0.90, 0.82, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.42}},
        {"name": MATERIAL_NAMES["lashes"], "doubleSided": True, "pbrMetallicRoughness": {"baseColorFactor": [0.025, 0.018, 0.014, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.78}},
    ])
    material_index = {"mouth": len(materials) - 3, "teeth": len(materials) - 2, "lashes": len(materials) - 1}
    binary = bytearray(binary_raw)

    def add_view(raw: bytes, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        return len(views) - 1

    def accessor(raw: bytes, *, component: int, count: int, kind: str, target: int) -> int:
        view = add_view(raw, target)
        accessors.append({"bufferView": view, "componentType": component, "count": count, "type": kind})
        return len(accessors) - 1

    gltf_primitives: list[dict[str, Any]] = []
    for role, positions, normals, faces, joint in primitives_source:
        if not positions or len(positions) != len(normals) or not faces:
            raise HighFidelityFaceSecondaryRuntimeError(f"face-secondary {role} geometry is empty")
        pos_raw = b"".join(struct.pack("<3f", *item) for item in positions)
        normal_raw = b"".join(struct.pack("<3f", *item) for item in normals)
        joints_raw = b"".join(struct.pack("<4H", joint, 0, 0, 0) for _ in positions)
        weights_raw = b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in positions)
        indices_flat = [index for tri in faces for index in tri]
        index_raw = b"".join(struct.pack("<I", index) for index in indices_flat)
        attrs = {
            "POSITION": accessor(pos_raw, component=5126, count=len(positions), kind="VEC3", target=34962),
            "NORMAL": accessor(normal_raw, component=5126, count=len(normals), kind="VEC3", target=34962),
            "JOINTS_0": accessor(joints_raw, component=5123, count=len(positions), kind="VEC4", target=34962),
            "WEIGHTS_0": accessor(weights_raw, component=5126, count=len(positions), kind="VEC4", target=34962),
        }
        mat = material_index["lashes" if "lash" in role else "teeth" if "teeth" in role else "mouth"]
        gltf_primitives.append({"attributes": attrs, "indices": accessor(index_raw, component=5125, count=len(indices_flat), kind="SCALAR", target=34963), "material": mat, "mode": 4, "extras": {"bodyrigFaceSecondaryRole": role}})

    meshes.append({"name": MESH_NAME, "primitives": gltf_primitives})
    mesh_index = len(meshes) - 1
    nodes.append({"name": NODE_NAME, "mesh": mesh_index, "skin": 0})
    scenes[0]["nodes"].append(len(nodes) - 1)
    buffers[0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary))


def build_runtime(package_path: str | Path, output_dir: str | Path, *, bodyrig_revision: str) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    if root.exists():
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary review runtime output is create-only")
    if not isinstance(bodyrig_revision, str) or len(bodyrig_revision) != 40 or any(ch not in "0123456789abcdef" for ch in bodyrig_revision):
        raise HighFidelityFaceSecondaryRuntimeError("BodyRig revision is not canonical")
    avatar, body_id, package_sha = _package_avatar(package)
    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HighFidelityFaceSecondaryRuntimeError(str(exc)) from exc
    bodyrig, top, face = _validate_source(document)

    joint_values = {name: _joint_world(document, name) for name in JOINT_NAMES}
    head_joint, head = joint_values["smplx_head"]
    jaw_joint, jaw = joint_values["smplx_jaw"]
    _left_joint, left_eye = joint_values["smplx_left_eye"]
    _right_joint, right_eye = joint_values["smplx_right_eye"]
    interocular = math.dist(left_eye, right_eye)
    if not math.isfinite(interocular) or not 0.015 <= interocular <= 0.20:
        raise HighFidelityFaceSecondaryRuntimeError("SMPL-X interocular scale is outside the accepted human range")
    eye_mid = tuple((left_eye[index] + right_eye[index]) * 0.5 for index in range(3))
    mouth = tuple(jaw[index] + (eye_mid[index] - jaw[index]) * 0.36 for index in range(3))
    mouth = (mouth[0], mouth[1], mouth[2] - interocular * 0.055)

    primitives: list[tuple[str, list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]] = []
    for role, geometry in (
        ("mouth_interior", _box(mouth, (interocular * 0.92, interocular * 0.23, interocular * 0.11), jaw_joint)),
        ("upper_teeth", _box((mouth[0], mouth[1] + interocular * 0.045, mouth[2] + interocular * 0.025), (interocular * 0.72, interocular * 0.075, interocular * 0.055), head_joint)),
        ("lower_teeth", _box((mouth[0], mouth[1] - interocular * 0.045, mouth[2] + interocular * 0.02), (interocular * 0.68, interocular * 0.065, interocular * 0.05), jaw_joint)),
        ("left_eyelashes", _lash(left_eye, interocular, head_joint)),
        ("right_eyelashes", _lash(right_eye, interocular, head_joint)),
    ):
        positions, normals, faces_value, joint = geometry
        primitives.append((role, positions, normals, faces_value, joint))

    review_vrm = _append_geometry(document, binary, primitives)
    appearance = bodyrig["appearanceTransfer"]
    eye = bodyrig["eyePromotion"]
    metadata = {
        "format": REVIEW_METADATA_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "sourcePackageSha256": package_sha,
        "sourceAvatarSha256": _sha256_bytes(avatar),
        "appearanceTransferSha256": _canonical_json_sha(appearance),
        "eyePromotionSha256": _canonical_json_sha(eye),
        "canonicalBodyId": body_id,
        "bodyrigRevision": bodyrig_revision,
        "smplxAnchorJoints": {name: value[0] for name, value in joint_values.items()},
        "interocularDistanceMeters": round(interocular, 8),
        "eyebrowAppearanceSource": "existing-source-derived-face-basecolor",
        "lipBoundarySource": "existing-source-derived-face-basecolor",
        "mouthInteriorGeometry": "deterministic-generic-secondary-anatomy-v1",
        "teethGeometry": "deterministic-generic-secondary-anatomy-v1",
        "eyelashGeometry": "deterministic-smplx-head-anchored-ribbon-v1",
        "semanticAnchorAuthority": "licensed-smplx-joint-topology-v1",
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "faceSecondaryComponentAuthority": False,
        "productionActivation": False,
    }
    try:
        review_document, review_binary = _read_glb(review_vrm)
    except PbrMaterialError as exc:
        raise HighFidelityFaceSecondaryRuntimeError(str(exc)) from exc
    review_bodyrig = _bodyrig(review_document)
    review_bodyrig["faceSecondaryReviewRuntime"] = metadata
    review_vrm = _write_glb(review_document, review_binary)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": bodyrig_revision,
        "canonicalBodyId": body_id,
        "sourcePackageSha256": package_sha,
        "sourceAvatarSha256": _sha256_bytes(avatar),
        "reviewVrmSha256": _sha256_bytes(review_vrm),
        "appearanceTransferSha256": metadata["appearanceTransferSha256"],
        "eyePromotionSha256": metadata["eyePromotionSha256"],
        "topComponentsBefore": dict(top["components"]),
        "faceSecondaryBefore": dict(face["components"]),
        "candidateComponents": {
            "eyebrow_appearance": "partial",
            "lip_boundary": "partial",
            "mouth_interior": "partial",
            "teeth": "partial",
            "eyelashes": "partial",
        },
        "semanticAnchorAuthority": metadata["semanticAnchorAuthority"],
        "genericSecondaryAnatomy": True,
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "faceSecondaryComponentAuthority": False,
        "packageMutationPerformed": False,
        "productionActivation": False,
    }
    root.mkdir(parents=True)
    try:
        (root / REVIEW_VRM_NAME).write_bytes(review_vrm)
        with (root / RECEIPT_NAME).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except Exception:
        for path in (root / REVIEW_VRM_NAME, root / RECEIPT_NAME):
            path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    return {**receipt, "reviewVrmPath": str(root / REVIEW_VRM_NAME), "receiptPath": str(root / RECEIPT_NAME)}


def read_runtime(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    vrm_path, receipt_path = root / REVIEW_VRM_NAME, root / RECEIPT_NAME
    if not vrm_path.is_file() or not receipt_path.is_file():
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary review runtime evidence is missing")
    try:
        value = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary runtime receipt is unreadable") from exc
    if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary runtime receipt format/version is invalid")
    if value.get("reviewVrmSha256") != _sha256_file(vrm_path):
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary review VRM bytes changed")
    if value.get("comparisonOnly") is not True or value.get("humanReviewRequired") is not True or value.get("faceSecondaryComponentAuthority") is not False or value.get("packageMutationPerformed") is not False or value.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryRuntimeError("face-secondary runtime crossed review-only authority")
    try:
        document, _binary = _read_glb(vrm_path.read_bytes())
    except PbrMaterialError as exc:
        raise HighFidelityFaceSecondaryRuntimeError(str(exc)) from exc
    bodyrig = _bodyrig(document)
    embedded = bodyrig.get("faceSecondaryReviewRuntime")
    if not isinstance(embedded, dict) or embedded.get("sourcePackageSha256") != value.get("sourcePackageSha256") or embedded.get("bodyrigRevision") != value.get("bodyrigRevision"):
        raise HighFidelityFaceSecondaryRuntimeError("embedded face-secondary runtime authority is stale")
    return {**value, "reviewVrmPath": str(vrm_path), "receiptPath": str(receipt_path)}
