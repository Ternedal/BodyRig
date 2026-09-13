from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .bridges.sith_pbr_material import PNG_SIGNATURE
from .fidelity_ab import FidelityAbError, _indices
from .hands_feet_nails_source_capture import REQUIRED_REGIONS, capture_dir
from .hands_feet_nails_uv_domain_evidence import (
    REGION_JOINT_NAMES,
    WEIGHT_THRESHOLD,
    HandsFeetNailsUvDomainEvidenceError,
    _accessor_values,
    _canonical_mesh,
    _region_domain,
)

METHOD = "source-closeup-luminance-residual-skinned-uv-v1"
DETAIL_STRENGTH = 0.50
GAUSSIAN_RADIUS = 2.0
EDGE_SUPPRESS_LEVEL = 40
MAX_CHANNEL_DELTA_LEVELS = 8
MIN_REGION_MASK_PIXELS = 24
MIN_REGION_CHANGED_PIXELS = 8
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


def _region_masks(
    document: Mapping[str, Any],
    binary: bytes,
    uv_evidence: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Image.Image]:
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
        draws[owners[0]].polygon(points, fill=255)

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


def _residual_map(source: Image.Image) -> Image.Image:
    gray = source.convert("L")
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=GAUSSIAN_RADIUS))
    raw, smooth = gray.tobytes(), blurred.tobytes()
    encoded = bytearray(len(raw))
    for index, (sample, baseline) in enumerate(zip(raw, smooth, strict=True)):
        residual = int(sample) - int(baseline)
        delta = 0 if abs(residual) > EDGE_SUPPRESS_LEVEL else int(round(residual * DETAIL_STRENGTH))
        encoded[index] = 128 + max(
            -MAX_CHANNEL_DELTA_LEVELS,
            min(MAX_CHANNEL_DELTA_LEVELS, delta),
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
    if observed_max > MAX_CHANNEL_DELTA_LEVELS:
        raise HandsFeetNailsDetailTextureError("HFN detail exceeded bounded channel delta")
    if changed < MIN_REGION_CHANGED_PIXELS:
        raise HandsFeetNailsDetailTextureError(
            "HFN source closeup does not contain enough bounded local detail for application"
        )
    result = base.copy()
    result.paste(Image.frombytes("RGB", size, bytes(pixels)), bbox[:2])
    return result, changed, observed_max


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
        current, changed, observed_max = _apply_region(
            current,
            mask=masks[region],
            source=source_image,
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
