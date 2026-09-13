from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import struct
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import (
    PbrMaterialError,
    _box_blur,
    _decode_rgb_png,
    _encode_rgb_png,
    _read_glb,
    _write_glb,
)
from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    evidence_path,
    validate_landmark_evidence,
)
from .hands_feet_nails_source_capture import (
    FORMAT as CAPTURE_FORMAT,
    POLICY_REVISION as CAPTURE_POLICY_REVISION,
    VERSION as CAPTURE_VERSION,
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    read_source_capture,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .package import MRBodyError, validate_package
from .person_profiles import PersonProfileError, load_profile

FORMAT = "bodyrig-hands-feet-nails-detail-candidate"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-detail-candidate-v1"
EMBEDDED_FORMAT = "bodyrig-hands-feet-nails-detail-candidate"
PACKAGE_NAME = "candidate.mrbody"
RECEIPT_NAME = "detail-candidate.json"
BODY_MESH_NAME = "BodyRigSourceDerivedMesh"
SOURCE_COORDINATE_AUTHORITY = "openpose-semantic-landmarks-explicit-crop"
METHOD = "source-patch-bounded-distal-uv-refinement-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_REV_RE = re.compile(r"^body-r[0-9]{4}$")

# First 55 SMPL-X LBS joints are part of the portable BodyRig skin contract.
# We intentionally target only the distal finger joints and the dedicated toe
# joints; wrists, ankles and proximal limbs are never mutation domains.
HAND_TARGETS: dict[str, tuple[tuple[str, int], ...]] = {
    "left_hand": (
        ("thumb", 39),
        ("index", 27),
        ("middle", 30),
        ("ring", 36),
        ("pinky", 33),
    ),
    "right_hand": (
        ("thumb", 54),
        ("index", 42),
        ("middle", 45),
        ("ring", 51),
        ("pinky", 48),
    ),
}
FOOT_TARGETS: dict[str, tuple[int, tuple[str, ...]]] = {
    "left_foot": (10, ("big_toe", "small_toe")),
    "right_foot": (11, ("big_toe", "small_toe")),
}
REQUIRED_REGIONS = ("left_hand", "right_hand", "left_foot", "right_foot")

TRIANGLE_MEAN_WEIGHT_THRESHOLD = 0.18
TRIANGLE_MAX_WEIGHT_THRESHOLD = 0.30
MAX_SINGLE_DOMAIN_FRACTION = 0.025
MAX_TOTAL_DOMAIN_FRACTION = 0.12
CHANNEL_DELTA_CAP = 0.05
COLOR_TRANSFER_GAIN = 0.35
DETAIL_TRANSFER_GAIN = 0.30
HAND_PATCH_RADIUS = 36
FOOT_PATCH_RADIUS = 56

_COMPONENT_DTYPE = {
    5121: "<u1",
    5123: "<u2",
    5125: "<u4",
    5126: "<f4",
}
_TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class HandsFeetNailsDetailCandidateError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise HandsFeetNailsDetailCandidateError(f"HFN detail input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HandsFeetNailsDetailCandidateError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HandsFeetNailsDetailCandidateError(f"{label} is not a canonical Git revision")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsDetailCandidateError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsDetailCandidateError(f"{label} must be a JSON object")
    return value


def _strict_capture(value: Mapping[str, Any]) -> dict[str, Any]:
    version = value.get("version")
    if (
        value.get("format") != CAPTURE_FORMAT
        or isinstance(version, bool)
        or version != CAPTURE_VERSION
        or value.get("policy_revision") != CAPTURE_POLICY_REVISION
    ):
        raise HandsFeetNailsDetailCandidateError("HFN source capture is not strict v1 authority")
    return dict(value)


def _array(document: Mapping[str, Any], field: str) -> list[Any]:
    value = document.get(field)
    if not isinstance(value, list):
        raise HandsFeetNailsDetailCandidateError(f"avatar glTF {field} array is missing")
    return value


def _indexed(values: list[Any], index: Any, *, label: str) -> dict[str, Any]:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(values):
        raise HandsFeetNailsDetailCandidateError(f"{label} index is invalid")
    value = values[index]
    if not isinstance(value, dict):
        raise HandsFeetNailsDetailCandidateError(f"{label} entry is invalid")
    return value


def _accessor_array(
    np: Any,
    document: Mapping[str, Any],
    binary: bytes,
    accessor_index: Any,
    *,
    label: str,
    expected_component: int | None = None,
    expected_type: str | None = None,
) -> tuple[Any, bytes]:
    accessors = _array(document, "accessors")
    views = _array(document, "bufferViews")
    accessor = _indexed(accessors, accessor_index, label=f"{label} accessor")
    if "sparse" in accessor or "bufferView" not in accessor:
        raise HandsFeetNailsDetailCandidateError(f"{label} accessor is not canonical")
    component = accessor.get("componentType")
    kind = accessor.get("type")
    count = accessor.get("count")
    if (
        component not in _COMPONENT_DTYPE
        or kind not in _TYPE_WIDTH
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
    ):
        raise HandsFeetNailsDetailCandidateError(f"{label} accessor type/count is invalid")
    if expected_component is not None and component != expected_component:
        raise HandsFeetNailsDetailCandidateError(f"{label} component type is not canonical")
    if expected_type is not None and kind != expected_type:
        raise HandsFeetNailsDetailCandidateError(f"{label} vector type is not canonical")
    if accessor.get("normalized", False) is not False:
        raise HandsFeetNailsDetailCandidateError(f"{label} normalized accessor is unsupported")

    view = _indexed(views, accessor.get("bufferView"), label=f"{label} bufferView")
    if view.get("buffer") != 0:
        raise HandsFeetNailsDetailCandidateError(f"{label} accessor does not use canonical GLB buffer")
    view_offset = view.get("byteOffset", 0)
    view_length = view.get("byteLength")
    accessor_offset = accessor.get("byteOffset", 0)
    dtype = np.dtype(_COMPONENT_DTYPE[component])
    width = _TYPE_WIDTH[kind]
    element_size = int(dtype.itemsize) * width
    stride = view.get("byteStride", element_size)
    for raw, name, minimum in (
        (view_offset, "view offset", 0),
        (view_length, "view length", 1),
        (accessor_offset, "accessor offset", 0),
        (stride, "byte stride", element_size),
    ):
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
            raise HandsFeetNailsDetailCandidateError(f"{label} {name} is invalid")
    if stride < element_size or view_offset + view_length > len(binary):
        raise HandsFeetNailsDetailCandidateError(f"{label} accessor range is invalid")
    start = view_offset + accessor_offset
    view_end = view_offset + view_length
    tight = bytearray()
    for item in range(count):
        begin = start + item * stride
        end = begin + element_size
        if end > view_end:
            raise HandsFeetNailsDetailCandidateError(f"{label} accessor exceeds bufferView")
        tight.extend(binary[begin:end])
    raw = bytes(tight)
    array = np.frombuffer(raw, dtype=dtype).reshape(count, width)
    return array.copy(), raw


def _body_primitive(np: Any, document: Mapping[str, Any], binary: bytes) -> dict[str, Any]:
    meshes = _array(document, "meshes")
    matches = [mesh for mesh in meshes if isinstance(mesh, dict) and mesh.get("name") == BODY_MESH_NAME]
    if len(matches) != 1:
        raise HandsFeetNailsDetailCandidateError("canonical BodyRig body mesh is missing or ambiguous")
    primitives = matches[0].get("primitives")
    if not isinstance(primitives, list) or len(primitives) != 1 or not isinstance(primitives[0], dict):
        raise HandsFeetNailsDetailCandidateError("canonical BodyRig body mesh primitive is invalid")
    primitive = primitives[0]
    if primitive.get("mode", 4) != 4:
        raise HandsFeetNailsDetailCandidateError("HFN detail requires triangular body primitive")
    attributes = primitive.get("attributes")
    if not isinstance(attributes, Mapping):
        raise HandsFeetNailsDetailCandidateError("body primitive attributes are missing")
    required = {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
    if not required.issubset(attributes):
        raise HandsFeetNailsDetailCandidateError("body primitive lacks portable UV/skinning attributes")

    positions, position_raw = _accessor_array(
        np, document, binary, attributes["POSITION"], label="POSITION", expected_component=5126, expected_type="VEC3"
    )
    normals, normal_raw = _accessor_array(
        np, document, binary, attributes["NORMAL"], label="NORMAL", expected_component=5126, expected_type="VEC3"
    )
    uv, uv_raw = _accessor_array(
        np, document, binary, attributes["TEXCOORD_0"], label="TEXCOORD_0", expected_component=5126, expected_type="VEC2"
    )
    joints, joints_raw = _accessor_array(
        np, document, binary, attributes["JOINTS_0"], label="JOINTS_0", expected_component=5123, expected_type="VEC4"
    )
    weights, weights_raw = _accessor_array(
        np, document, binary, attributes["WEIGHTS_0"], label="WEIGHTS_0", expected_component=5126, expected_type="VEC4"
    )
    indices, indices_raw = _accessor_array(
        np, document, binary, primitive.get("indices"), label="indices", expected_type="SCALAR"
    )
    if indices.dtype not in (np.dtype("<u2"), np.dtype("<u4")):
        raise HandsFeetNailsDetailCandidateError("body triangle indices must be unsigned 16/32-bit")
    vertex_count = len(uv)
    if not all(len(value) == vertex_count for value in (positions, normals, joints, weights)):
        raise HandsFeetNailsDetailCandidateError("body attribute vertex counts disagree")
    flat_indices = indices.reshape(-1).astype(np.int64, copy=False)
    if len(flat_indices) % 3 != 0 or bool(np.any(flat_indices < 0)) or bool(np.any(flat_indices >= vertex_count)):
        raise HandsFeetNailsDetailCandidateError("body triangle index topology is invalid")
    if not bool(np.all(np.isfinite(uv))) or bool(np.any(uv < -1e-6)) or bool(np.any(uv > 1.000001)):
        raise HandsFeetNailsDetailCandidateError("body UV coordinates are outside canonical 0..1 range")
    if not bool(np.all(np.isfinite(weights))) or bool(np.any(weights < -1e-6)):
        raise HandsFeetNailsDetailCandidateError("body skin weights are invalid")

    digest = hashlib.sha256()
    for name, raw in (
        ("POSITION", position_raw),
        ("NORMAL", normal_raw),
        ("TEXCOORD_0", uv_raw),
        ("JOINTS_0", joints_raw),
        ("WEIGHTS_0", weights_raw),
        ("indices", indices_raw),
    ):
        digest.update(name.encode("ascii") + b"\x00" + raw)
    return {
        "primitive": primitive,
        "positions": positions,
        "uv": uv.astype(np.float32, copy=False),
        "joints": joints.astype(np.int64, copy=False),
        "weights": weights.astype(np.float32, copy=False),
        "indices": flat_indices,
        "geometry_fingerprint_sha256": digest.hexdigest(),
    }


def _basecolor_binding(document: Mapping[str, Any], binary: bytes) -> tuple[dict[str, Any], bytes]:
    meshes = _array(document, "meshes")
    body_mesh = next((mesh for mesh in meshes if isinstance(mesh, dict) and mesh.get("name") == BODY_MESH_NAME), None)
    if not isinstance(body_mesh, dict):
        raise HandsFeetNailsDetailCandidateError("body mesh is missing for material binding")
    primitive = body_mesh["primitives"][0]
    material = _indexed(_array(document, "materials"), primitive.get("material"), label="body material")
    pbr = material.get("pbrMetallicRoughness")
    texture_info = pbr.get("baseColorTexture") if isinstance(pbr, Mapping) else None
    if not isinstance(texture_info, Mapping):
        raise HandsFeetNailsDetailCandidateError("body material lacks baseColorTexture")
    texture = _indexed(_array(document, "textures"), texture_info.get("index"), label="baseColor texture")
    image = _indexed(_array(document, "images"), texture.get("source"), label="baseColor image")
    if image.get("mimeType") != "image/png":
        raise HandsFeetNailsDetailCandidateError("body baseColor image must be embedded PNG")
    view = _indexed(_array(document, "bufferViews"), image.get("bufferView"), label="baseColor image bufferView")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if (
        view.get("buffer") != 0
        or isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length < 1
        or offset + length > len(binary)
    ):
        raise HandsFeetNailsDetailCandidateError("body baseColor image byte range is invalid")
    return image, binary[offset:offset + length]


def _joint_influence(np: Any, joints: Any, weights: Any, joint_index: int) -> Any:
    return np.sum(np.where(joints == int(joint_index), weights, 0.0), axis=1).astype(np.float32, copy=False)


def _rasterize_joint_domain(
    np: Any,
    *,
    uv: Any,
    indices: Any,
    influence: Any,
    width: int,
    height: int,
    label: str,
) -> Any:
    faces = indices.reshape(-1, 3)
    face_weights = influence[faces]
    selected = faces[
        (face_weights.max(axis=1) >= TRIANGLE_MAX_WEIGHT_THRESHOLD)
        & (face_weights.mean(axis=1) >= TRIANGLE_MEAN_WEIGHT_THRESHOLD)
    ]
    if len(selected) == 0:
        raise HandsFeetNailsDetailCandidateError(f"{label} has no distal UV triangles")
    mask = np.zeros((height, width), dtype=bool)
    for face in selected:
        tri_uv = uv[face]
        # A seam-wrapping triangle can otherwise paint a huge atlas rectangle.
        if float(np.ptp(tri_uv[:, 0])) > 0.50 or float(np.ptp(tri_uv[:, 1])) > 0.50:
            continue
        x = tri_uv[:, 0] * float(width - 1)
        y = (1.0 - tri_uv[:, 1]) * float(height - 1)
        x0 = max(0, int(math.floor(float(x.min()))))
        x1 = min(width - 1, int(math.ceil(float(x.max()))))
        y0 = max(0, int(math.floor(float(y.min()))))
        y1 = min(height - 1, int(math.ceil(float(y.max()))))
        if x1 < x0 or y1 < y0:
            continue
        denom = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(float(denom)) < 1e-8:
            continue
        gx, gy = np.meshgrid(
            np.arange(x0, x1 + 1, dtype=np.float32),
            np.arange(y0, y1 + 1, dtype=np.float32),
        )
        a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / denom
        b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / denom
        c = 1.0 - a - b
        inside = (a >= -1e-5) & (b >= -1e-5) & (c >= -1e-5)
        mask[y0:y1 + 1, x0:x1 + 1] |= inside
    count = int(mask.sum())
    if count < 3:
        raise HandsFeetNailsDetailCandidateError(f"{label} distal UV mask is implausibly small")
    fraction = count / float(width * height)
    if fraction > MAX_SINGLE_DOMAIN_FRACTION:
        raise HandsFeetNailsDetailCandidateError(
            f"{label} distal UV mask is too broad for bounded HFN mutation ({fraction:.6f})"
        )
    return mask


def _feather_mask(np: Any, mask: Any) -> Any:
    padded = np.pad(mask.astype(np.float32), ((1, 1), (1, 1)), mode="constant")
    neighbor_sum = np.zeros(mask.shape, dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            neighbor_sum += padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    alpha = np.clip(neighbor_sum / 9.0, 0.0, 1.0)
    return alpha * mask.astype(np.float32)


def _source_patch(np: Any, closeup_rgb: Any, projection: Mapping[str, Any], labels: Sequence[str], *, radius: int) -> Any:
    landmarks = projection.get("landmarks")
    if not isinstance(landmarks, Mapping):
        raise HandsFeetNailsDetailCandidateError("HFN projection landmarks are missing")
    points: list[tuple[int, int]] = []
    height, width = closeup_rgb.shape[:2]
    for label in labels:
        value = landmarks.get(label)
        if not isinstance(value, Mapping):
            raise HandsFeetNailsDetailCandidateError(f"source landmark is missing: {label}")
        x_norm = value.get("x_norm")
        y_norm = value.get("y_norm")
        if (
            isinstance(x_norm, bool)
            or not isinstance(x_norm, (int, float))
            or isinstance(y_norm, bool)
            or not isinstance(y_norm, (int, float))
            or not 0.0 <= float(x_norm) <= 1.0
            or not 0.0 <= float(y_norm) <= 1.0
        ):
            raise HandsFeetNailsDetailCandidateError(f"source landmark coordinates are invalid: {label}")
        points.append((int(round(float(x_norm) * (width - 1))), int(round(float(y_norm) * (height - 1)))))
    x0 = max(0, min(point[0] for point in points) - radius)
    x1 = min(width, max(point[0] for point in points) + radius + 1)
    y0 = max(0, min(point[1] for point in points) - radius)
    y1 = min(height, max(point[1] for point in points) + radius + 1)
    patch = closeup_rgb[y0:y1, x0:x1]
    if patch.ndim != 3 or patch.shape[2] != 3 or patch.shape[0] < 8 or patch.shape[1] < 8:
        raise HandsFeetNailsDetailCandidateError("source landmark patch is implausibly small")
    return patch.astype(np.float32) / 255.0


def _resample_residual(np: Any, residual: Any, *, width: int, height: int) -> Any:
    ys = np.rint(np.linspace(0, residual.shape[0] - 1, height)).astype(np.int64)
    xs = np.rint(np.linspace(0, residual.shape[1] - 1, width)).astype(np.int64)
    return residual[ys[:, None], xs[None, :]]


def _apply_source_patch(
    np: Any,
    base: Any,
    mask: Any,
    patch: Any,
    *,
    label: str,
) -> dict[str, Any]:
    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        raise HandsFeetNailsDetailCandidateError(f"{label} mutation mask is empty")
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    current = base[mask]
    current_mean = current.mean(axis=0)
    source_mean = patch.reshape(-1, 3).mean(axis=0)
    color_shift = np.clip((source_mean - current_mean) * COLOR_TRANSFER_GAIN, -CHANNEL_DELTA_CAP * 0.70, CHANNEL_DELTA_CAP * 0.70)

    luma = 0.2126 * patch[:, :, 0] + 0.7152 * patch[:, :, 1] + 0.0722 * patch[:, :, 2]
    residual = luma - _box_blur(np, luma, 2)
    residual = np.clip(residual * DETAIL_TRANSFER_GAIN, -CHANNEL_DELTA_CAP * 0.55, CHANNEL_DELTA_CAP * 0.55)
    mapped = _resample_residual(np, residual, width=x1 - x0 + 1, height=y1 - y0 + 1)
    local_mask = mask[y0:y1 + 1, x0:x1 + 1]
    alpha = _feather_mask(np, local_mask)
    local = base[y0:y1 + 1, x0:x1 + 1]
    delta = color_shift[None, None, :] + mapped[:, :, None]
    delta = np.clip(delta, -CHANNEL_DELTA_CAP, CHANNEL_DELTA_CAP) * alpha[:, :, None]
    before = local.copy()
    local[local_mask] = np.clip(local[local_mask] + delta[local_mask], 0.0, 1.0)
    observed = np.abs(local - before)
    max_delta = float(observed.max())
    changed = int(np.count_nonzero(np.max(observed, axis=2) >= (1.0 / 255.0)))
    if not math.isfinite(max_delta) or max_delta > CHANNEL_DELTA_CAP + 1e-6:
        raise HandsFeetNailsDetailCandidateError(f"{label} exceeded bounded source-detail channel delta")
    return {
        "target_pixel_count": int(mask.sum()),
        "changed_pixel_count": changed,
        "max_observed_channel_delta": round(max_delta, 6),
        "source_patch_mean_rgb": [round(float(value), 6) for value in source_mean],
        "target_pre_mean_rgb": [round(float(value), 6) for value in current_mean],
    }


def _closeup_rgb(np: Any, value: bytes, *, label: str) -> Any:
    try:
        rgb = _decode_rgb_png(np, value)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(f"{label} source closeup is invalid: {exc}") from exc
    if rgb.shape[0] != 1024 or rgb.shape[1] != 1024:
        raise HandsFeetNailsDetailCandidateError(f"{label} source closeup must be canonical 1024x1024")
    return rgb


def apply_hfn_detail_to_avatar(
    avatar_vrm: bytes,
    *,
    evidence: Mapping[str, Any],
    evidence_sha256: str,
    source_package_sha256: str,
    canonical_body_id: str,
    closeup_png: Mapping[str, bytes],
    candidate_bodyrig_revision: str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise HandsFeetNailsDetailCandidateError("numpy is required for bounded HFN detail application") from exc

    validated = validate_landmark_evidence(evidence)
    if validated.get("all_regions_application_ready") is not True:
        raise HandsFeetNailsDetailCandidateError("HFN landmark evidence is not application-ready for all four regions")
    if validated.get("package_application_authority") is not False or validated.get("production_activation") is not False:
        raise HandsFeetNailsDetailCandidateError("HFN landmark evidence crossed its pre-application authority boundary")
    evidence_sha = _sha(evidence_sha256, label="HFN landmark evidence SHA-256")
    source_package_sha = _sha(source_package_sha256, label="source package SHA-256")
    revision = _revision(candidate_bodyrig_revision, label="candidate BodyRig revision")
    body_id = str(canonical_body_id or "").strip()
    if not body_id:
        raise HandsFeetNailsDetailCandidateError("canonical body id is missing")
    if set(closeup_png) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsDetailCandidateError("HFN detail application requires all four exact source closeups")

    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, dict):
        raise HandsFeetNailsDetailCandidateError("avatar lacks mutable BodyRig metadata")
    if "handsFeetNailsDetailCandidate" in bodyrig:
        raise HandsFeetNailsDetailCandidateError("avatar already carries HFN detail-candidate metadata")

    mesh = _body_primitive(np, document, binary)
    geometry_fingerprint = mesh["geometry_fingerprint_sha256"]
    image, source_basecolor_png = _basecolor_binding(document, binary)
    try:
        base_u8 = _decode_rgb_png(np, source_basecolor_png)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(f"body baseColor PNG is invalid: {exc}") from exc
    base = base_u8.astype(np.float32) / 255.0
    height, width = base.shape[:2]
    if width < 256 or height < 256:
        raise HandsFeetNailsDetailCandidateError("body baseColor atlas is too small for bounded HFN detail application")

    closeups = {
        region: _closeup_rgb(np, closeup_png[region], label=region)
        for region in REQUIRED_REGIONS
    }
    masks: dict[str, Any] = {}
    metrics: dict[str, dict[str, Any]] = {}
    union = np.zeros((height, width), dtype=bool)

    for capture_region, targets in HAND_TARGETS.items():
        projection = validated["regions"][capture_region]["projection"]
        if projection.get("source_coordinate_authority") != SOURCE_COORDINATE_AUTHORITY:
            raise HandsFeetNailsDetailCandidateError(f"{capture_region} coordinate authority is not canonical")
        for semantic_label, joint_index in targets:
            key = f"{capture_region}:{semantic_label}"
            influence = _joint_influence(np, mesh["joints"], mesh["weights"], joint_index)
            mask = _rasterize_joint_domain(
                np,
                uv=mesh["uv"],
                indices=mesh["indices"],
                influence=influence,
                width=width,
                height=height,
                label=key,
            )
            patch = _source_patch(
                np,
                closeups[capture_region],
                projection,
                (semantic_label,),
                radius=HAND_PATCH_RADIUS,
            )
            metrics[key] = _apply_source_patch(np, base, mask, patch, label=key)
            masks[key] = mask
            union |= mask

    for capture_region, (joint_index, labels) in FOOT_TARGETS.items():
        projection = validated["regions"][capture_region]["projection"]
        if projection.get("source_coordinate_authority") != SOURCE_COORDINATE_AUTHORITY:
            raise HandsFeetNailsDetailCandidateError(f"{capture_region} coordinate authority is not canonical")
        influence = _joint_influence(np, mesh["joints"], mesh["weights"], joint_index)
        mask = _rasterize_joint_domain(
            np,
            uv=mesh["uv"],
            indices=mesh["indices"],
            influence=influence,
            width=width,
            height=height,
            label=f"{capture_region}:toes",
        )
        patch = _source_patch(
            np,
            closeups[capture_region],
            projection,
            labels,
            radius=FOOT_PATCH_RADIUS,
        )
        key = f"{capture_region}:toes"
        metrics[key] = _apply_source_patch(np, base, mask, patch, label=key)
        masks[key] = mask
        union |= mask

    union_count = int(union.sum())
    union_fraction = union_count / float(width * height)
    if union_fraction > MAX_TOTAL_DOMAIN_FRACTION:
        raise HandsFeetNailsDetailCandidateError(
            f"combined HFN UV domain is too broad ({union_fraction:.6f})"
        )
    refined_u8 = np.clip(base * 255.0 + 0.5, 0, 255).astype(np.uint8)
    refined_png = _encode_rgb_png(np, refined_u8)
    source_basecolor_sha = _sha256_bytes(source_basecolor_png)
    refined_basecolor_sha = _sha256_bytes(refined_png)
    if refined_basecolor_sha == source_basecolor_sha:
        raise HandsFeetNailsDetailCandidateError("bounded HFN application produced no baseColor byte change")

    new_binary = bytearray(binary)
    while len(new_binary) % 4:
        new_binary.append(0)
    offset = len(new_binary)
    new_binary.extend(refined_png)
    views = _array(document, "bufferViews")
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(refined_png)})
    image["bufferView"] = len(views) - 1
    image["mimeType"] = "image/png"
    image["name"] = "BodyRigHFNSourceDetailCandidate"
    document["buffers"][0]["byteLength"] = len(new_binary)

    embedded = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "method": METHOD,
        "personId": str(validated["person_id"]),
        "bodyRevision": str(validated["body_revision"]),
        "captureId": str(validated["capture_id"]),
        "landmarkEvidenceSha256": evidence_sha,
        "sourcePackageSha256": source_package_sha,
        "canonicalBodyId": body_id,
        "sourceBaseColorSha256": source_basecolor_sha,
        "refinedBaseColorSha256": refined_basecolor_sha,
        "portableGeometryFingerprintSha256": geometry_fingerprint,
        "candidateBodyRigRevision": revision,
        "targetPixelCount": union_count,
        "targetPixelFraction": round(union_fraction, 8),
        "channelDeltaCap": CHANNEL_DELTA_CAP,
        "sourceDerived": True,
        "genericGuessingPermitted": False,
        "geometryMutationPerformed": False,
        "packageMutationPerformed": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    bodyrig["handsFeetNailsDetailCandidate"] = embedded
    try:
        promoted = _write_glb(document, bytes(new_binary))
        check_document, check_binary = _read_glb(promoted)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    after_mesh = _body_primitive(np, check_document, check_binary)
    if after_mesh["geometry_fingerprint_sha256"] != geometry_fingerprint:
        raise HandsFeetNailsDetailCandidateError("HFN candidate changed portable geometry/UV/skinning bytes")

    max_delta = max(float(item["max_observed_channel_delta"]) for item in metrics.values())
    result = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "method": METHOD,
        "person_id": str(validated["person_id"]),
        "body_revision": str(validated["body_revision"]),
        "capture_id": str(validated["capture_id"]),
        "landmark_evidence_sha256": evidence_sha,
        "source_package_sha256": source_package_sha,
        "canonical_body_id": body_id,
        "source_basecolor_sha256": source_basecolor_sha,
        "refined_basecolor_sha256": refined_basecolor_sha,
        "portable_geometry_fingerprint_sha256": geometry_fingerprint,
        "candidate_bodyrig_revision": revision,
        "target_pixel_count": union_count,
        "target_pixel_fraction": round(union_fraction, 8),
        "max_observed_channel_delta": round(max_delta, 6),
        "domains": metrics,
        "source_paths_persisted": False,
        "source_derived": True,
        "generic_guessing_permitted": False,
        "geometry_mutation_performed": False,
        "package_mutation_performed": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    return promoted, result


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsDetailCandidateError("could not read source HFN package") from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise HandsFeetNailsDetailCandidateError("source HFN package lacks canonical avatar/checksum files")
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate package is create-only") from exc
    except OSError as exc:
        raise HandsFeetNailsDetailCandidateError("could not write HFN detail candidate package") from exc


def _registered_body(profile: Mapping[str, Any], body_revision: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == body_revision:
            return dict(item)
    raise HandsFeetNailsDetailCandidateError("HFN body revision is not registered on this Person")


def write_detail_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    landmark_bodyrig_revision: str,
    source_package_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    candidate_bodyrig_revision: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_REV_RE.fullmatch(body):
        raise HandsFeetNailsDetailCandidateError("HFN Person/body identity is not canonical")
    candidate_revision = _revision(candidate_bodyrig_revision, label="candidate BodyRig revision")
    landmark_revision = _revision(landmark_bodyrig_revision, label="landmark BodyRig revision")
    final_root = Path(output_dir).expanduser().resolve()
    if final_root.exists():
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate output is create-only")

    try:
        profile = load_profile(root_path, person)
        registered = _registered_body(profile, body)
    except PersonProfileError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    registered_body_id = str(registered.get("body_id") or "").strip()
    if not registered_body_id:
        raise HandsFeetNailsDetailCandidateError("registered body revision has no canonical body id")

    landmark_path = evidence_path(root_path, person, body, capture_id, landmark_revision)
    landmark_value = validate_landmark_evidence(_read_json(landmark_path, label="HFN landmark evidence"))
    if (
        landmark_value["person_id"] != person
        or landmark_value["body_revision"] != body
        or landmark_value["capture_id"] != str(capture_id).strip().lower()
        or landmark_value["evidence_bodyrig_revision"] != landmark_revision
    ):
        raise HandsFeetNailsDetailCandidateError("HFN landmark evidence identity changed")
    landmark_sha = _sha256_file(landmark_path)

    try:
        capture = _strict_capture(
            read_source_capture(
                root_path,
                person,
                body_revision=body,
                capture_id=str(capture_id).strip().lower(),
            )
        )
    except HandsFeetNailsSourceCaptureError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    capture_root = capture_dir(root_path, person, body, str(capture_id).strip().lower())
    capture_manifest = capture_root / "source-capture.json"
    if _sha256_file(capture_manifest) != _sha(landmark_value.get("source_capture_sha256"), label="landmark source-capture SHA-256"):
        raise HandsFeetNailsDetailCandidateError("HFN source capture bytes changed after landmark evidence")

    closeups: dict[str, bytes] = {}
    for region in REQUIRED_REGIONS:
        item = capture["regions"][region]
        image = (capture_root / str(item["image"])).resolve()
        try:
            image.relative_to(capture_root.resolve())
        except ValueError as exc:
            raise HandsFeetNailsDetailCandidateError(f"{region} source closeup escaped capture root") from exc
        actual = _sha256_file(image)
        expected = _sha(landmark_value["regions"][region]["closeup_image_sha256"], label=f"{region} landmark closeup SHA-256")
        if actual != expected or actual != _sha(item.get("image_sha256"), label=f"{region} capture image SHA-256"):
            raise HandsFeetNailsDetailCandidateError(f"{region} source closeup bytes changed")
        closeups[region] = image.read_bytes()

    source_package = Path(source_package_path).expanduser().resolve()
    if not source_package.is_file():
        raise HandsFeetNailsDetailCandidateError("source promoted high-fidelity package is missing")
    try:
        validated_package = validate_package(source_package)
        audit_before = audit_high_fidelity_package(source_package)
    except (MRBodyError, HighFidelityPackageAuditError) as exc:
        raise HandsFeetNailsDetailCandidateError(f"source HFN package failed strict audit: {exc}") from exc
    body_id = str(validated_package.manifest["id"])
    if body_id != registered_body_id:
        raise HandsFeetNailsDetailCandidateError("source promoted package belongs to a different registered body identity")
    if audit_before.get("high_fidelity_ready") is not True:
        raise HandsFeetNailsDetailCandidateError("HFN detail application requires completed high-fidelity promoted body lineage")
    if audit_before.get("production_ready") is not False:
        raise HandsFeetNailsDetailCandidateError("source package unexpectedly carries production authority")
    source_package_sha = _sha256_file(source_package)
    try:
        with zipfile.ZipFile(source_package, "r") as archive:
            source_avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise HandsFeetNailsDetailCandidateError("could not read source package avatar.vrm") from exc

    promoted_avatar, candidate = apply_hfn_detail_to_avatar(
        source_avatar,
        evidence=landmark_value,
        evidence_sha256=landmark_sha,
        source_package_sha256=source_package_sha,
        canonical_body_id=body_id,
        closeup_png=closeups,
        candidate_bodyrig_revision=candidate_revision,
    )

    final_root.parent.mkdir(parents=True, exist_ok=True)
    staging = final_root.with_name(f".{final_root.name}.partial-{uuid.uuid4().hex}")
    staging.mkdir(parents=False, exist_ok=False)
    package_path = staging / PACKAGE_NAME
    receipt_path = staging / RECEIPT_NAME
    moved = False
    try:
        _rewrite_package(source_package, package_path, avatar_vrm=promoted_avatar)
        try:
            validated_after = validate_package(package_path)
            audit_after = audit_high_fidelity_package(package_path)
        except (MRBodyError, HighFidelityPackageAuditError) as exc:
            raise HandsFeetNailsDetailCandidateError(f"HFN candidate package failed strict audit: {exc}") from exc
        if str(validated_after.manifest["id"]) != body_id:
            raise HandsFeetNailsDetailCandidateError("HFN candidate changed canonical body id")
        if audit_after.get("components") != audit_before.get("components"):
            raise HandsFeetNailsDetailCandidateError("HFN candidate changed high-fidelity component authority")
        if audit_after.get("face_secondary_components") != audit_before.get("face_secondary_components"):
            raise HandsFeetNailsDetailCandidateError("HFN candidate changed face-secondary authority")
        if audit_after.get("production_ready") is not False:
            raise HandsFeetNailsDetailCandidateError("HFN candidate crossed production authority boundary")

        receipt = {
            **candidate,
            "source_capture_sha256": _sha256_file(capture_manifest),
            "source_manifest_sha256": _sha(capture.get("source_manifest_sha256"), label="source manifest SHA-256"),
            "candidate_package_sha256": _sha256_file(package_path),
            "candidate_avatar_sha256": _sha256_bytes(promoted_avatar),
        }
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, final_root)
        moved = True
        return {
            **receipt,
            "package_path": str(final_root / PACKAGE_NAME),
            "receipt_path": str(final_root / RECEIPT_NAME),
        }
    finally:
        if not moved:
            shutil.rmtree(staging, ignore_errors=True)
