from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping

from sith_pbr_material import (
    PNG_SIGNATURE,
    PbrMaterialError,
    _box_blur,
    _decode_rgb_png,
    _encode_rgb_png,
    _read_glb,
    _write_glb,
)

DETAIL_STRENGTH = 0.45
CHANNEL_DELTA_CAP = 0.035
METHOD = "source-luminance-bounded-detail-v1"


class BaseColorDetailError(ValueError):
    pass


def derive_basecolor_detail(np: Any, texture_png: bytes) -> tuple[bytes, dict[str, float | str | bool]]:
    """Restore restrained local luminance definition from the exact source texture.

    This is deterministic source-derived sharpening, not synthesis. Only a
    high-pass luminance residual is added back to RGB equally per channel, which
    preserves source chroma apart from unavoidable clipping. Every channel delta
    is capped to roughly 9/255 so this layer cannot invent strong new markings or
    facial features.
    """

    try:
        rgb_u8 = _decode_rgb_png(np, texture_png)
    except PbrMaterialError as exc:
        raise BaseColorDetailError(str(exc)) from exc
    rgb = rgb_u8.astype(np.float32) / 255.0
    luminance = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    smooth = _box_blur(np, luminance, 2)
    detail = luminance - smooth

    # Avoid amplifying clipping-prone highlights and shadows. Midtones retain
    # full detail strength; deep shadows/highlights fade the effect smoothly.
    headroom = np.minimum(luminance, 1.0 - luminance)
    headroom_gate = np.clip(headroom / 0.16, 0.0, 1.0)
    delta = np.clip(detail * DETAIL_STRENGTH, -CHANNEL_DELTA_CAP, CHANNEL_DELTA_CAP) * headroom_gate
    refined = np.clip(rgb + delta[:, :, None], 0.0, 1.0)
    refined_u8 = np.clip(refined * 255.0 + 0.5, 0, 255).astype(np.uint8)

    observed = np.abs(refined_u8.astype(np.int16) - rgb_u8.astype(np.int16)).astype(np.float32) / 255.0
    max_delta = float(observed.max())
    mean_delta = float(observed.mean())
    changed_fraction = float((observed.max(axis=2) >= (1.0 / 255.0)).mean())
    quantized_cap = CHANNEL_DELTA_CAP + (1.0 / 255.0) + 1e-9
    if not all(math.isfinite(value) for value in (max_delta, mean_delta, changed_fraction)):
        raise BaseColorDetailError("base-color detail metrics are non-finite")
    if max_delta > quantized_cap:
        raise BaseColorDetailError(
            f"base-color detail exceeded bounded channel delta (observed={max_delta:.6f}, cap={quantized_cap:.6f})"
        )

    refined_png = _encode_rgb_png(np, refined_u8)
    metrics: dict[str, float | str | bool] = {
        "method": METHOD,
        "detail_strength": DETAIL_STRENGTH,
        "channel_delta_cap": CHANNEL_DELTA_CAP,
        "max_observed_channel_delta": round(max_delta, 6),
        "mean_abs_channel_delta": round(mean_delta, 6),
        "changed_pixel_fraction": round(changed_fraction, 6),
        "source_basecolor_sha256": hashlib.sha256(texture_png).hexdigest(),
        "refined_basecolor_sha256": hashlib.sha256(refined_png).hexdigest(),
        "source_derived": True,
        "generative": False,
    }
    return refined_png, metrics


def _metric_float(metrics: Mapping[str, object], name: str, *, minimum: float, maximum: float) -> float:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BaseColorDetailError(f"base-color detail metric {name} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise BaseColorDetailError(f"base-color detail metric {name} is outside the accepted range")
    return result


def refine_glb_basecolor(
    avatar_vrm: bytes,
    *,
    refined_basecolor_png: bytes,
    metrics: Mapping[str, object],
) -> bytes:
    """Replace texture-0 image bytes with a bounded source-derived refinement.

    Texture/image indices are preserved so VRM thumbnail and PBR texture indices
    remain stable. The original embedded base-color bytes are verified against
    the source hash before the new bufferView is published.
    """

    if not isinstance(refined_basecolor_png, bytes) or not refined_basecolor_png.startswith(PNG_SIGNATURE):
        raise BaseColorDetailError("refined base-color texture is not PNG")
    if metrics.get("method") != METHOD or metrics.get("source_derived") is not True or metrics.get("generative") is not False:
        raise BaseColorDetailError("base-color detail provenance contract is invalid")

    source_sha = metrics.get("source_basecolor_sha256")
    refined_sha = metrics.get("refined_basecolor_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise BaseColorDetailError("source base-color SHA-256 is invalid")
    actual_refined_sha = hashlib.sha256(refined_basecolor_png).hexdigest()
    if refined_sha != actual_refined_sha:
        raise BaseColorDetailError("refined base-color SHA-256 does not match metrics")

    detail_strength = _metric_float(metrics, "detail_strength", minimum=0.0, maximum=1.0)
    channel_delta_cap = _metric_float(metrics, "channel_delta_cap", minimum=0.0, maximum=0.08)
    max_observed = _metric_float(metrics, "max_observed_channel_delta", minimum=0.0, maximum=0.08)
    mean_abs = _metric_float(metrics, "mean_abs_channel_delta", minimum=0.0, maximum=0.08)
    changed_fraction = _metric_float(metrics, "changed_pixel_fraction", minimum=0.0, maximum=1.0)
    if max_observed > channel_delta_cap + (1.0 / 255.0) + 1e-6:
        raise BaseColorDetailError("refined base-color metrics exceed the declared channel delta cap")

    try:
        document, binary_bytes = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise BaseColorDetailError(str(exc)) from exc
    images = document.get("images")
    textures = document.get("textures")
    views = document.get("bufferViews")
    materials = document.get("materials")
    if not isinstance(images, list) or len(images) < 4 or not isinstance(images[0], dict):
        raise BaseColorDetailError("base-color detail requires the completed BodyRig PBR image contract")
    if not isinstance(textures, list) or len(textures) < 3 or not isinstance(textures[0], dict) or textures[0].get("source") != 0:
        raise BaseColorDetailError("base-color texture index contract is invalid")
    if not isinstance(views, list) or not isinstance(materials, list) or len(materials) != 1 or not isinstance(materials[0], dict):
        raise BaseColorDetailError("base-color detail GLB contract is invalid")
    pbr = materials[0].get("pbrMetallicRoughness")
    if not isinstance(pbr, dict) or pbr.get("baseColorTexture") != {"index": 0}:
        raise BaseColorDetailError("base-color material contract is invalid")

    extras = document.get("extras")
    if not isinstance(extras, dict) or not isinstance(extras.get("bodyrig"), dict):
        raise BaseColorDetailError("BodyRig PBR provenance is missing")
    bodyrig = extras["bodyrig"]
    if "materialRefinement" not in bodyrig:
        raise BaseColorDetailError("base-color detail requires prior PBR material refinement")
    if "baseColorDetailRefinement" in bodyrig:
        raise BaseColorDetailError("BodyRig base-color detail refinement is already present")

    base_image = images[0]
    view_index = base_image.get("bufferView")
    if isinstance(view_index, bool) or not isinstance(view_index, int) or view_index < 0 or view_index >= len(views):
        raise BaseColorDetailError("embedded base-color bufferView is invalid")
    view = views[view_index]
    if not isinstance(view, dict):
        raise BaseColorDetailError("embedded base-color bufferView is invalid")
    offset = int(view.get("byteOffset", 0))
    length = view.get("byteLength")
    if isinstance(length, bool) or not isinstance(length, int) or offset < 0 or length < 1 or offset + length > len(binary_bytes):
        raise BaseColorDetailError("embedded base-color byte range is invalid")
    embedded_source = binary_bytes[offset:offset + length]
    if hashlib.sha256(embedded_source).hexdigest() != source_sha:
        raise BaseColorDetailError("embedded base-color does not match the exact source texture")

    binary = bytearray(binary_bytes)
    while len(binary) % 4:
        binary.append(0)
    refined_offset = len(binary)
    binary.extend(refined_basecolor_png)
    views.append({"buffer": 0, "byteOffset": refined_offset, "byteLength": len(refined_basecolor_png)})
    base_image["bufferView"] = len(views) - 1
    base_image["mimeType"] = "image/png"
    base_image["name"] = "BodyRigSourceDerivedBaseColorDetail"

    bodyrig["baseColorDetailRefinement"] = {
        "method": METHOD,
        "sourceBaseColorSha256": source_sha,
        "refinedBaseColorSha256": actual_refined_sha,
        "detailStrength": detail_strength,
        "channelDeltaCap": channel_delta_cap,
        "maxObservedChannelDelta": max_observed,
        "meanAbsChannelDelta": mean_abs,
        "changedPixelFraction": changed_fraction,
        "sourceDerived": True,
        "generative": False,
    }
    document["buffers"][0]["byteLength"] = len(binary)
    try:
        return _write_glb(document, bytes(binary))
    except PbrMaterialError as exc:
        raise BaseColorDetailError(str(exc)) from exc
