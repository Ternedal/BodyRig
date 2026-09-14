from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .bridges.sith_pbr_material import PNG_SIGNATURE
from .fidelity_ab import FidelityAbError, _indices
from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    evidence_path as landmark_evidence_path,
    validate_landmark_evidence,
)
from .hands_feet_nails_source_capture import REQUIRED_REGIONS, capture_dir
from .hands_feet_nails_toenail_domain import (
    FOOT_REGIONS,
    TOE_LABELS,
    HandsFeetNailsToenailDomainError,
    toe_source_landmarks,
    toenail_triangle_groups,
)
from .hands_feet_nails_uv_domain_evidence import (
    REGION_JOINT_NAMES,
    WEIGHT_THRESHOLD,
    HandsFeetNailsUvDomainEvidenceError,
    _accessor_values,
    _canonical_mesh,
    _region_domain,
)

METHOD = "source-landmark-fingernail-toenail-residual-skinned-uv-v3"
DETAIL_STRENGTH = 0.50
GAUSSIAN_RADIUS = 2.0
EDGE_SUPPRESS_LEVEL = 40
RESIDUAL_MAX_CHANNEL_DELTA_LEVELS = 8
NAIL_MAX_CHANNEL_DELTA_LEVELS = 16
MAX_CHANNEL_DELTA_LEVELS = RESIDUAL_MAX_CHANNEL_DELTA_LEVELS + NAIL_MAX_CHANNEL_DELTA_LEVELS
NAIL_BLEND_STRENGTH = 0.58
NAIL_PATCH_RADIUS_FRACTION = 0.055
NAIL_DISTAL_WEIGHT_THRESHOLD = 0.10
MIN_NAIL_MASK_PIXELS = 6
MIN_REGION_MASK_PIXELS = 24
MIN_REGION_CHANGED_PIXELS = 8
HAND_NAIL_JOINTS = {
    "left_hand": {
        "thumb": "smplx_left_thumb3",
        "index": "smplx_left_index3",
        "middle": "smplx_left_middle3",
        "ring": "smplx_left_ring3",
        "pinky": "smplx_left_pinky3",
    },
    "right_hand": {
        "thumb": "smplx_right_thumb3",
        "index": "smplx_right_index3",
        "middle": "smplx_right_middle3",
        "ring": "smplx_right_ring3",
        "pinky": "smplx_right_pinky3",
    },
}
REGION_METRIC_FIELDS = {
    "source_image_sha256",
    "uv_set_sha256",
    "mask_pixel_count",
    "changed_pixel_count",
    "max_observed_channel_delta_levels",
}


class HandsFeetNailsDetailTextureError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HandsFeetNailsDetailTextureError(f"HFN detail requires canonical glTF {name}")
    return value


def _body_uv_inputs(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
) -> tuple[list[tuple[float | int, ...]], list[tuple[float | int, ...]], list[tuple[float | int, ...]], list[int], list[str]]:
    mesh_index, skin_index, primitive_index, primitive, _joint_nodes, joint_names = _canonical_mesh(document)
    mesh = _array(document, "meshes")[mesh_index]
    if (
        uv_evidence.get("mesh_index"),
        uv_evidence.get("skin_index"),
        uv_evidence.get("primitive_index"),
        uv_evidence.get("mesh_name"),
    ) != (mesh_index, skin_index, primitive_index, mesh.get("name")):
        raise HandsFeetNailsDetailTextureError(
            "HFN UV-domain evidence no longer matches canonical body mesh/skin"
        )
    if primitive.get("mode", 4) != 4:
        raise HandsFeetNailsDetailTextureError("HFN detail requires triangle-list body primitive")
    attrs = primitive.get("attributes")
    if not isinstance(attrs, dict):
        raise HandsFeetNailsDetailTextureError("HFN body primitive attributes are missing")
    try:
        uvs = _accessor_values(
            document, binary, attrs["TEXCOORD_0"],
            label="body TEXCOORD_0", component_type=5126, kind="VEC2",
        )
        joints = _accessor_values(
            document, binary, attrs["JOINTS_0"],
            label="body JOINTS_0", component_type=5123, kind="VEC4",
        )
        weights = _accessor_values(
            document, binary, attrs["WEIGHTS_0"],
            label="body WEIGHTS_0", component_type=5126, kind="VEC4",
        )
    except (KeyError, HandsFeetNailsUvDomainEvidenceError) as exc:
        raise HandsFeetNailsDetailTextureError("HFN body UV/skinning accessors are invalid") from exc
    if not (len(uvs) == len(joints) == len(weights)):
        raise HandsFeetNailsDetailTextureError("HFN body UV/skinning accessor counts differ")
    try:
        indices = _indices(document, binary, primitive, len(uvs))
    except FidelityAbError as exc:
        raise HandsFeetNailsDetailTextureError(str(exc)) from exc
    if len(indices) % 3:
        raise HandsFeetNailsDetailTextureError("HFN body triangle index count is invalid")
    return uvs, joints, weights, indices, joint_names


def _draw_uv_triangle(
    draw: ImageDraw.ImageDraw,
    *,
    triangle: list[int],
    uvs: list[tuple[float | int, ...]],
    width: int,
    height: int,
) -> None:
    points: list[tuple[int, int]] = []
    for vertex in triangle:
        u, v = float(uvs[vertex][0]), float(uvs[vertex][1])
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise HandsFeetNailsDetailTextureError(
                "HFN body UV escaped normalized texture bounds"
            )
        points.append((
            min(width - 1, max(0, int(round(u * (width - 1))))),
            min(height - 1, max(0, int(round(v * (height - 1))))),
        ))
    draw.polygon(points, fill=255)


def _region_masks(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Image.Image]:
    uvs, joints, weights, indices, joint_names = _body_uv_inputs(document, binary, uv_evidence)

    memberships: dict[str, list[bool]] = {}
    for region in REQUIRED_REGIONS:
        expected = uv_evidence["regions"][region]
        actual = _region_domain(
            capture_region=region,
            semantic_region=expected["semantic_region"],
            target_names=REGION_JOINT_NAMES[region],
            joint_names=joint_names,
            uvs=uvs,
            joints=joints,
            weights=weights,
        )
        if actual != expected:
            raise HandsFeetNailsDetailTextureError(
                f"{region} UV domain no longer matches exact package vertices"
            )
        target = set(actual["target_joint_indices"])
        memberships[region] = [
            sum(
                float(weight)
                for joint, weight in zip(joint_row, weight_row, strict=True)
                if int(joint) in target
            ) >= WEIGHT_THRESHOLD
            for joint_row, weight_row in zip(joints, weights, strict=True)
        ]

    masks = {region: Image.new("L", (width, height), 0) for region in REQUIRED_REGIONS}
    draws = {region: ImageDraw.Draw(mask) for region, mask in masks.items()}
    for offset in range(0, len(indices), 3):
        triangle = indices[offset : offset + 3]
        owners = [
            region for region in REQUIRED_REGIONS
            if all(memberships[region][vertex] for vertex in triangle)
        ]
        if len(owners) > 1:
            raise HandsFeetNailsDetailTextureError(
                "HFN body triangle belongs to overlapping detail regions"
            )
        if not owners:
            continue
        _draw_uv_triangle(
            draws[owners[0]], triangle=triangle, uvs=uvs, width=width, height=height
        )

    union = Image.new("L", (width, height), 0)
    for region in REQUIRED_REGIONS:
        mask = masks[region]
        if mask.histogram()[255] < MIN_REGION_MASK_PIXELS:
            raise HandsFeetNailsDetailTextureError(
                f"{region} HFN texture mask is too small for bounded detail application"
            )
        if ImageChops.multiply(union, mask).getbbox() is not None:
            raise HandsFeetNailsDetailTextureError("HFN texture masks overlap")
        union = ImageChops.lighter(union, mask)
    return masks


def _fingernail_masks(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
    region_masks: Mapping[str, Image.Image],
    *,
    width: int,
    height: int,
) -> dict[str, dict[str, Image.Image]]:
    uvs, joints, weights, indices, joint_names = _body_uv_inputs(document, binary, uv_evidence)
    result: dict[str, dict[str, Image.Image]] = {}
    for region, nail_joints in HAND_NAIL_JOINTS.items():
        region_result: dict[str, Image.Image] = {}
        for label, joint_name in nail_joints.items():
            if joint_name not in joint_names:
                raise HandsFeetNailsDetailTextureError(
                    f"{region} fingernail target joint is missing: {joint_name}"
                )
            joint_index = joint_names.index(joint_name)
            membership = [
                sum(
                    float(weight)
                    for joint, weight in zip(joint_row, weight_row, strict=True)
                    if int(joint) == joint_index
                ) >= NAIL_DISTAL_WEIGHT_THRESHOLD
                for joint_row, weight_row in zip(joints, weights, strict=True)
            ]
            distal = Image.new("L", (width, height), 0)
            draw = ImageDraw.Draw(distal)
            for offset in range(0, len(indices), 3):
                triangle = indices[offset : offset + 3]
                if all(membership[vertex] for vertex in triangle):
                    _draw_uv_triangle(
                        draw, triangle=triangle, uvs=uvs, width=width, height=height
                    )
            distal = ImageChops.multiply(distal, region_masks[region])
            bbox = distal.getbbox()
            if bbox is None:
                raise HandsFeetNailsDetailTextureError(
                    f"{region} {label} distal UV domain is missing"
                )
            x0, y0, x1, y1 = bbox
            span_x, span_y = x1 - x0, y1 - y0
            inset_x = max(1, int(round(span_x * 0.20)))
            inset_y = max(1, int(round(span_y * 0.20)))
            ellipse = Image.new("L", (width, height), 0)
            ellipse_draw = ImageDraw.Draw(ellipse)
            ellipse_draw.ellipse(
                (
                    x0 + inset_x,
                    y0 + inset_y,
                    max(x0 + inset_x + 1, x1 - inset_x),
                    max(y0 + inset_y + 1, y1 - inset_y),
                ),
                fill=255,
            )
            nail = ImageChops.multiply(distal, ellipse)
            if nail.histogram()[255] < MIN_NAIL_MASK_PIXELS:
                nail = distal
            if nail.histogram()[255] < MIN_NAIL_MASK_PIXELS:
                raise HandsFeetNailsDetailTextureError(
                    f"{region} {label} fingernail UV mask is too small"
                )
            region_result[label] = nail
        result[region] = region_result
    return result


def _toenail_masks(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
    region_masks: Mapping[str, Image.Image],
    *,
    width: int,
    height: int,
) -> dict[str, dict[str, Image.Image]]:
    uvs, _joints, _weights, _indices_all, _joint_names = _body_uv_inputs(document, binary, uv_evidence)
    try:
        groups = toenail_triangle_groups(document, binary, uv_evidence)
    except HandsFeetNailsToenailDomainError as exc:
        raise HandsFeetNailsDetailTextureError(str(exc)) from exc
    result: dict[str, dict[str, Image.Image]] = {}
    for region in FOOT_REGIONS:
        region_result: dict[str, Image.Image] = {}
        for label in TOE_LABELS:
            key = f"{region}_{label}"
            triangles = groups.get(key)
            if not isinstance(triangles, list) or not triangles:
                raise HandsFeetNailsDetailTextureError(f"{key} toenail target domain is missing")
            nail = Image.new("L", (width, height), 0)
            draw = ImageDraw.Draw(nail)
            for triangle in triangles:
                _draw_uv_triangle(draw, triangle=triangle, uvs=uvs, width=width, height=height)
            nail = ImageChops.multiply(nail, region_masks[region])
            if nail.histogram()[255] < MIN_NAIL_MASK_PIXELS:
                raise HandsFeetNailsDetailTextureError(f"{key} toenail UV mask is too small")
            region_result[label] = nail
        result[region] = region_result
    return result


def _read_landmark_evidence(
    source_root: Path,
    uv_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    required = (
        "person_id",
        "body_revision",
        "capture_id",
        "landmark_evidence_bodyrig_revision",
        "landmark_evidence_sha256",
    )
    if any(not uv_evidence.get(field) for field in required):
        raise HandsFeetNailsDetailTextureError(
            "HFN UV evidence lacks exact landmark-evidence authority"
        )
    path = landmark_evidence_path(
        source_root,
        str(uv_evidence["person_id"]),
        str(uv_evidence["body_revision"]),
        str(uv_evidence["capture_id"]),
        str(uv_evidence["landmark_evidence_bodyrig_revision"]),
    )
    if not path.is_file() or _sha256_file(path) != uv_evidence["landmark_evidence_sha256"]:
        raise HandsFeetNailsDetailTextureError(
            "HFN landmark evidence bytes no longer match UV evidence authority"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        landmark = validate_landmark_evidence(raw)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        HandsFeetNailsLandmarkEvidenceError,
    ) as exc:
        raise HandsFeetNailsDetailTextureError("HFN landmark evidence is invalid") from exc
    if landmark.get("all_regions_application_ready") is not True:
        raise HandsFeetNailsDetailTextureError(
            "HFN fingernail application requires all landmark regions to be ready"
        )
    return landmark


def _residual_map(source: Image.Image) -> Image.Image:
    gray = source.convert("L")
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=GAUSSIAN_RADIUS))
    raw, smooth = gray.tobytes(), blurred.tobytes()
    encoded = bytearray(len(raw))
    for index, (sample, baseline) in enumerate(zip(raw, smooth, strict=True)):
        residual = int(sample) - int(baseline)
        delta = 0 if abs(residual) > EDGE_SUPPRESS_LEVEL else int(round(residual * DETAIL_STRENGTH))
        encoded[index] = 128 + max(
            -RESIDUAL_MAX_CHANNEL_DELTA_LEVELS,
            min(RESIDUAL_MAX_CHANNEL_DELTA_LEVELS, delta),
        )
    return Image.frombytes("L", gray.size, bytes(encoded))


def _apply_region(
    base: Image.Image,
    *,
    mask: Image.Image,
    source: Image.Image,
) -> tuple[Image.Image, int, int]:
    bbox = mask.getbbox()
    if bbox is None or bbox[2] - bbox[0] < 2 or bbox[3] - bbox[1] < 2:
        raise HandsFeetNailsDetailTextureError("HFN texture mask has no usable bounding box")
    size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    residual = _residual_map(source).resize(size, Image.Resampling.BICUBIC)
    mask_bytes = mask.crop(bbox).tobytes()
    residual_bytes = residual.tobytes()
    pixels = bytearray(base.crop(bbox).convert("RGB").tobytes())
    changed = 0
    observed_max = 0
    for pixel_index, coverage in enumerate(mask_bytes):
        if coverage == 0:
            continue
        delta = int(residual_bytes[pixel_index]) - 128
        if delta == 0:
            continue
        start = pixel_index * 3
        before = pixels[start : start + 3]
        after = [max(0, min(255, int(channel) + delta)) for channel in before]
        observed = max(abs(after[i] - before[i]) for i in range(3))
        if observed:
            pixels[start : start + 3] = bytes(after)
            changed += 1
            observed_max = max(observed_max, observed)
    if observed_max > RESIDUAL_MAX_CHANNEL_DELTA_LEVELS:
        raise HandsFeetNailsDetailTextureError("HFN residual detail exceeded bounded channel delta")
    if changed < MIN_REGION_CHANGED_PIXELS:
        raise HandsFeetNailsDetailTextureError(
            "HFN source closeup does not contain enough bounded local detail for application"
        )
    result = base.copy()
    result.paste(Image.frombytes("RGB", size, bytes(pixels)), bbox[:2])
    return result, changed, observed_max


def _landmark_patch(source: Image.Image, landmark: Mapping[str, Any]) -> Image.Image:
    try:
        x = float(landmark["x_norm"])
        y = float(landmark["y_norm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HandsFeetNailsDetailTextureError("HFN fingernail landmark is invalid") from exc
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise HandsFeetNailsDetailTextureError("HFN fingernail landmark escaped source closeup")
    width, height = source.size
    radius = max(8, int(round(min(width, height) * NAIL_PATCH_RADIUS_FRACTION)))
    cx = int(round(x * (width - 1)))
    cy = int(round(y * (height - 1)))
    left, top = max(0, cx - radius), max(0, cy - radius)
    right, bottom = min(width, cx + radius + 1), min(height, cy + radius + 1)
    if right - left < 4 or bottom - top < 4:
        raise HandsFeetNailsDetailTextureError("HFN fingernail source patch is too small")
    return source.crop((left, top, right, bottom)).convert("RGB")


def _apply_nail_patch(
    base: Image.Image,
    *,
    mask: Image.Image,
    patch: Image.Image,
) -> Image.Image:
    bbox = mask.getbbox()
    if bbox is None:
        raise HandsFeetNailsDetailTextureError("HFN fingernail UV mask is empty")
    size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    if size[0] < 1 or size[1] < 1:
        raise HandsFeetNailsDetailTextureError("HFN fingernail UV mask has invalid bounds")
    source = patch.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    target = base.crop(bbox).convert("RGB")
    mask_bytes = mask.crop(bbox).tobytes()
    source_bytes = source.tobytes()
    target_bytes = bytearray(target.tobytes())
    for pixel_index, coverage in enumerate(mask_bytes):
        if coverage == 0:
            continue
        start = pixel_index * 3
        alpha = (coverage / 255.0) * NAIL_BLEND_STRENGTH
        for channel in range(3):
            before = int(target_bytes[start + channel])
            desired = int(source_bytes[start + channel])
            delta = int(round((desired - before) * alpha))
            delta = max(
                -NAIL_MAX_CHANNEL_DELTA_LEVELS,
                min(NAIL_MAX_CHANNEL_DELTA_LEVELS, delta),
            )
            target_bytes[start + channel] = max(0, min(255, before + delta))
    result = base.copy()
    result.paste(Image.frombytes("RGB", size, bytes(target_bytes)), bbox[:2])
    return result


def _change_metrics(
    before: Image.Image,
    after: Image.Image,
    *,
    mask: Image.Image,
) -> tuple[int, int]:
    if before.size != after.size or before.size != mask.size:
        raise HandsFeetNailsDetailTextureError("HFN change-metric image sizes differ")
    left = before.convert("RGB").tobytes()
    right = after.convert("RGB").tobytes()
    mask_bytes = mask.tobytes()
    changed = 0
    observed_max = 0
    for pixel_index, coverage in enumerate(mask_bytes):
        if coverage == 0:
            continue
        start = pixel_index * 3
        observed = max(abs(int(right[start + i]) - int(left[start + i])) for i in range(3))
        if observed:
            changed += 1
            observed_max = max(observed_max, observed)
    return changed, observed_max


def _encode_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(
        output,
        format="PNG",
        compress_level=9,
        optimize=False,
    )
    value = output.getvalue()
    if not value.startswith(PNG_SIGNATURE):
        raise HandsFeetNailsDetailTextureError("HFN detail encoder did not produce PNG")
    return value


def apply_source_details(
    document: Mapping[str, Any],
    binary: bytes,
    *,
    basecolor_png: bytes,
    uv_evidence: Mapping[str, Any],
    source_capture: Mapping[str, Any],
    source_root: Path,
) -> tuple[bytes, dict[str, dict[str, Any]], int, float]:
    try:
        with Image.open(io.BytesIO(basecolor_png)) as image:
            base = image.convert("RGB").copy()
    except (OSError, ValueError) as exc:
        raise HandsFeetNailsDetailTextureError("HFN active base-color PNG is unreadable") from exc
    width, height = base.size
    if width < 64 or height < 64 or width > 8192 or height > 8192:
        raise HandsFeetNailsDetailTextureError("HFN active base-color dimensions are unsupported")
    masks = _region_masks(document, binary, uv_evidence, width=width, height=height)
    nail_masks = _fingernail_masks(
        document,
        binary,
        uv_evidence,
        masks,
        width=width,
        height=height,
    )
    toenail_masks = _toenail_masks(
        document,
        binary,
        uv_evidence,
        masks,
        width=width,
        height=height,
    )
    landmark_evidence = _read_landmark_evidence(source_root, uv_evidence)
    current = base
    metrics: dict[str, dict[str, Any]] = {}
    total_changed = 0
    capture_root = capture_dir(
        source_root,
        source_capture["person_id"],
        source_capture["body_revision"],
        source_capture["capture_id"],
    )
    for region in REQUIRED_REGIONS:
        item = source_capture["regions"][region]
        path = (capture_root / item["image"]).resolve()
        try:
            path.relative_to(capture_root.resolve())
        except ValueError as exc:
            raise HandsFeetNailsDetailTextureError(
                f"{region} source closeup escaped capture root"
            ) from exc
        if _sha256_file(path) != item["image_sha256"]:
            raise HandsFeetNailsDetailTextureError(f"{region} source closeup bytes changed")
        try:
            with Image.open(path) as image:
                source_image = image.convert("RGB").copy()
        except (OSError, ValueError) as exc:
            raise HandsFeetNailsDetailTextureError(f"{region} source closeup is unreadable") from exc
        if source_image.size != (1024, 1024):
            raise HandsFeetNailsDetailTextureError(
                f"{region} source closeup is not canonical 1024x1024"
            )

        before_region = current
        current, _residual_changed, _residual_max = _apply_region(
            current,
            mask=masks[region],
            source=source_image,
        )
        if region in HAND_NAIL_JOINTS:
            projection = landmark_evidence["regions"][region]["projection"]
            landmarks = projection.get("landmarks") if isinstance(projection, Mapping) else None
            if not isinstance(landmarks, Mapping):
                raise HandsFeetNailsDetailTextureError(
                    f"{region} fingernail landmarks are missing"
                )
            for label in HAND_NAIL_JOINTS[region]:
                landmark = landmarks.get(label)
                if not isinstance(landmark, Mapping):
                    raise HandsFeetNailsDetailTextureError(
                        f"{region} {label} fingernail landmark is missing"
                    )
                current = _apply_nail_patch(
                    current,
                    mask=nail_masks[region][label],
                    patch=_landmark_patch(source_image, landmark),
                )
        elif region in FOOT_REGIONS:
            projection = landmark_evidence["regions"][region]["projection"]
            try:
                landmarks = toe_source_landmarks(projection)
            except HandsFeetNailsToenailDomainError as exc:
                raise HandsFeetNailsDetailTextureError(str(exc)) from exc
            for label in TOE_LABELS:
                current = _apply_nail_patch(
                    current,
                    mask=toenail_masks[region][label],
                    patch=_landmark_patch(source_image, landmarks[label]),
                )

        changed, observed_max = _change_metrics(before_region, current, mask=masks[region])
        if changed < MIN_REGION_CHANGED_PIXELS:
            raise HandsFeetNailsDetailTextureError(
                f"{region} source detail did not produce enough bounded target changes"
            )
        if observed_max > MAX_CHANNEL_DELTA_LEVELS:
            raise HandsFeetNailsDetailTextureError(
                f"{region} source detail exceeded global channel-delta cap"
            )
        metrics[region] = {
            "source_image_sha256": item["image_sha256"],
            "uv_set_sha256": uv_evidence["regions"][region]["uv_set_sha256"],
            "mask_pixel_count": masks[region].histogram()[255],
            "changed_pixel_count": changed,
            "max_observed_channel_delta_levels": observed_max,
        }
        total_changed += changed

    before, after = base.tobytes(), current.tobytes()
    changed_pixels = 0
    global_max = 0
    for offset in range(0, len(before), 3):
        observed = max(abs(after[offset + i] - before[offset + i]) for i in range(3))
        if observed:
            changed_pixels += 1
            global_max = max(global_max, observed)
    if changed_pixels != total_changed:
        raise HandsFeetNailsDetailTextureError("HFN region change accounting is inconsistent")
    if global_max > MAX_CHANNEL_DELTA_LEVELS:
        raise HandsFeetNailsDetailTextureError("HFN candidate exceeded global channel-delta cap")
    return (
        _encode_png(current),
        metrics,
        changed_pixels,
        changed_pixels / float(width * height),
    )
