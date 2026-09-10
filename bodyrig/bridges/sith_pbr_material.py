from __future__ import annotations

import binascii
import hashlib
import json
import math
import struct
import zlib
from typing import Any, Mapping

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"
BIN_CHUNK = b"BIN\x00"
PBR_METHOD = "source-basecolor-linear-highpass-pbr-v3"
PBR_COLOR_TRANSFER = "srgb-eotf-linear-light"
PBR_NORMAL_SCALE = 0.25
PBR_ROUGHNESS_BASE = 0.68
PBR_ROUGHNESS_DETAIL_GAIN = 0.10
PBR_ROUGHNESS_MIN = 0.64
PBR_ROUGHNESS_MAX = 0.82
PBR_METRIC_FIELDS = {
    "method",
    "base_color_transfer",
    "normal_scale",
    "roughness_min",
    "roughness_max",
    "roughness_mean",
    "normal_texture_sha256",
    "metallic_roughness_texture_sha256",
}


class PbrMaterialError(ValueError):
    pass


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_rgb_png(np: Any, value: bytes) -> Any:
    if not isinstance(value, bytes) or not value.startswith(PNG_SIGNATURE):
        raise PbrMaterialError("source texture is not PNG")
    offset = len(PNG_SIGNATURE)
    ihdr = None
    idat = bytearray()
    seen_iend = False
    while offset + 12 <= len(value):
        length = struct.unpack(">I", value[offset:offset + 4])[0]
        kind = value[offset + 4:offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(value):
            raise PbrMaterialError("source PNG chunk is truncated")
        payload = value[payload_start:payload_end]
        expected_crc = struct.unpack(">I", value[payload_end:crc_end])[0]
        if (binascii.crc32(kind + payload) & 0xFFFFFFFF) != expected_crc:
            raise PbrMaterialError("source PNG chunk CRC mismatch")
        if kind == b"IHDR":
            if ihdr is not None or length != 13:
                raise PbrMaterialError("source PNG IHDR is invalid")
            ihdr = payload
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            seen_iend = True
            break
        offset = crc_end
    if ihdr is None or not idat or not seen_iend:
        raise PbrMaterialError("source PNG is incomplete")

    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    if width < 1 or height < 1 or width > 8192 or height > 8192:
        raise PbrMaterialError("source PNG dimensions are outside the accepted range")
    if bit_depth != 8 or color_type not in {2, 6} or compression != 0 or filtering != 0 or interlace != 0:
        raise PbrMaterialError("PBR refinement requires non-interlaced 8-bit RGB/RGBA PNG")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PbrMaterialError("source PNG IDAT could not be decompressed") from exc
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise PbrMaterialError("source PNG decompressed byte count mismatch")

    rows = bytearray(height * stride)
    previous = bytearray(stride)
    source_offset = 0
    for y in range(height):
        filter_type = raw[source_offset]
        source_offset += 1
        encoded = raw[source_offset:source_offset + stride]
        source_offset += stride
        row = bytearray(stride)
        if filter_type not in {0, 1, 2, 3, 4}:
            raise PbrMaterialError("source PNG uses an unsupported row filter")
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            sample = encoded[x]
            if filter_type == 0:
                value_byte = sample
            elif filter_type == 1:
                value_byte = (sample + left) & 0xFF
            elif filter_type == 2:
                value_byte = (sample + up) & 0xFF
            elif filter_type == 3:
                value_byte = (sample + ((left + up) // 2)) & 0xFF
            else:
                value_byte = (sample + _paeth(left, up, upper_left)) & 0xFF
            row[x] = value_byte
        rows[y * stride:(y + 1) * stride] = row
        previous = row

    array = np.frombuffer(bytes(rows), dtype=np.uint8).reshape(height, width, channels)
    return array[:, :, :3].copy()


def _encode_rgb_png(np: Any, rgb: Any) -> bytes:
    if getattr(rgb, "ndim", None) != 3 or rgb.shape[2] != 3:
        raise PbrMaterialError("derived PBR texture must be HxWx3")
    height, width, _ = rgb.shape
    if width < 1 or height < 1 or width > 8192 or height > 8192:
        raise PbrMaterialError("derived PBR texture dimensions are invalid")
    pixels = np.asarray(rgb, dtype=np.uint8)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(pixels[y].tobytes())
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


def _box_blur(np: Any, value: Any, radius: int) -> Any:
    if radius < 1:
        return value.copy()
    size = 2 * radius + 1
    padded = np.pad(value, ((radius, radius), (radius, radius)), mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    total = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    return total / float(size * size)


def _srgb_to_linear(np: Any, value: Any) -> Any:
    """Decode normalized sRGB base-color samples to linear-light RGB."""
    srgb = np.asarray(value, dtype=np.float32)
    if not np.all(np.isfinite(srgb)) or np.any(srgb < 0.0) or np.any(srgb > 1.0):
        raise PbrMaterialError("sRGB base-color samples must be finite and normalized")
    return np.where(
        srgb <= 0.04045,
        srgb / 12.92,
        ((srgb + 0.055) / 1.055) ** 2.4,
    ).astype(np.float32)


def _roughness_from_detail(np: Any, detail: Any) -> Any:
    """Map only local high-frequency detail to conservative dielectric roughness."""
    micro = np.clip(np.abs(detail) / 0.12, 0.0, 1.0)
    roughness = PBR_ROUGHNESS_BASE + PBR_ROUGHNESS_DETAIL_GAIN * micro
    return np.clip(roughness, PBR_ROUGHNESS_MIN, PBR_ROUGHNESS_MAX)


def derive_pbr_maps(np: Any, texture_png: bytes) -> tuple[bytes, bytes, dict[str, float | str]]:
    """Derive restrained source-bound PBR detail in linear light.

    V2 stopped turning dark/saturated source pixels into glossy skin, but it
    still computed luminance/high-pass gradients directly in gamma-encoded
    sRGB. That disproportionately amplified dark source/projection contrast
    into synthetic normal and roughness detail.

    V3 first decodes the exact sRGB base color to linear-light RGB, then derives
    luminance/high-pass detail. Metallic remains zero, local detail can only
    increase roughness, and the restrained v2 normal scale is preserved.

    This remains a deterministic source-derived heuristic, not a physical skin
    measurement and not a substitute for later dedicated skin/SSS authority.
    """

    rgb_u8 = _decode_rgb_png(np, texture_png)
    srgb = rgb_u8.astype(np.float32) / 255.0
    rgb = _srgb_to_linear(np, srgb)
    luminance = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    smooth = _box_blur(np, luminance, 2)
    detail = luminance - smooth

    gradient_y, gradient_x = np.gradient(detail)
    normal_strength = 6.0
    nx = -gradient_x * normal_strength
    ny = -gradient_y * normal_strength
    nz = np.ones_like(nx)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    length = np.maximum(length, 1e-8)
    normal = np.stack((nx / length, ny / length, nz / length), axis=2)
    normal_rgb = np.clip((normal * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype(np.uint8)

    # Base-color darkness/saturation are lighting/appearance signals, not
    # physical surface-smoothness measurements. Local linear-light source
    # detail can only make the heuristic slightly rougher.
    roughness = _roughness_from_detail(np, detail)
    metallic_roughness = np.empty_like(rgb_u8)
    metallic_roughness[:, :, 0] = 255
    metallic_roughness[:, :, 1] = np.clip(roughness * 255.0 + 0.5, 0, 255).astype(np.uint8)
    metallic_roughness[:, :, 2] = 0

    normal_png = _encode_rgb_png(np, normal_rgb)
    metallic_roughness_png = _encode_rgb_png(np, metallic_roughness)
    metrics: dict[str, float | str] = {
        "method": PBR_METHOD,
        "base_color_transfer": PBR_COLOR_TRANSFER,
        "normal_scale": PBR_NORMAL_SCALE,
        "roughness_min": round(float(roughness.min()), 6),
        "roughness_max": round(float(roughness.max()), 6),
        "roughness_mean": round(float(roughness.mean()), 6),
        "normal_texture_sha256": hashlib.sha256(normal_png).hexdigest(),
        "metallic_roughness_texture_sha256": hashlib.sha256(metallic_roughness_png).hexdigest(),
    }
    if not all(math.isfinite(float(metrics[field])) for field in ("normal_scale", "roughness_min", "roughness_max", "roughness_mean")):
        raise PbrMaterialError("derived PBR metrics are non-finite")
    return normal_png, metallic_roughness_png, metrics


def _pad4(data: bytes, pad: bytes) -> bytes:
    return data + pad * ((-len(data)) % 4)


def _read_glb(value: bytes) -> tuple[dict[str, Any], bytes]:
    if not isinstance(value, bytes) or len(value) < 20 or value[:4] != GLB_MAGIC:
        raise PbrMaterialError("avatar is not a GLB/VRM")
    version, declared_length = struct.unpack("<II", value[4:12])
    if version != 2 or declared_length != len(value):
        raise PbrMaterialError("avatar GLB header is invalid")
    offset = 12
    document = None
    binary = b""
    while offset + 8 <= len(value):
        length, kind = struct.unpack("<I4s", value[offset:offset + 8])
        offset += 8
        end = offset + length
        if end > len(value):
            raise PbrMaterialError("avatar GLB chunk is truncated")
        payload = value[offset:end]
        offset = end
        if kind == JSON_CHUNK:
            if document is not None:
                raise PbrMaterialError("avatar GLB contains multiple JSON chunks")
            try:
                document = json.loads(payload.rstrip(b" \x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PbrMaterialError("avatar GLB JSON is invalid") from exc
        elif kind == BIN_CHUNK:
            if binary:
                raise PbrMaterialError("avatar GLB contains multiple BIN chunks")
            binary = payload
    if not isinstance(document, dict):
        raise PbrMaterialError("avatar GLB has no JSON document")
    buffers = document.get("buffers")
    if not isinstance(buffers, list) or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise PbrMaterialError("avatar GLB buffer contract is unsupported")
    byte_length = buffers[0].get("byteLength")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 0 or byte_length > len(binary):
        raise PbrMaterialError("avatar GLB buffer byteLength is invalid")
    return document, binary[:byte_length]


def _write_glb(document: Mapping[str, Any], binary: bytes) -> bytes:
    json_chunk = _pad4(
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        b" ",
    )
    bin_chunk = _pad4(binary, b"\x00")
    chunks = struct.pack("<I4s", len(json_chunk), JSON_CHUNK) + json_chunk
    if bin_chunk:
        chunks += struct.pack("<I4s", len(bin_chunk), BIN_CHUNK) + bin_chunk
    return GLB_MAGIC + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _validate_refinement_metrics(metrics: Mapping[str, float | str]) -> tuple[float, float, float, float]:
    if set(metrics) != PBR_METRIC_FIELDS:
        raise PbrMaterialError("PBR refinement receipt fields do not match canonical v3")
    if metrics.get("method") != PBR_METHOD:
        raise PbrMaterialError("PBR refinement receipt method is stale or unsupported")
    if metrics.get("base_color_transfer") != PBR_COLOR_TRANSFER:
        raise PbrMaterialError("PBR refinement receipt base-color transfer is stale or unsupported")

    values: dict[str, float] = {}
    for field in ("normal_scale", "roughness_min", "roughness_max", "roughness_mean"):
        raw = metrics.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise PbrMaterialError(f"PBR {field} is invalid")
        value = float(raw)
        if not math.isfinite(value):
            raise PbrMaterialError(f"PBR {field} must be finite")
        values[field] = value

    normal_scale = values["normal_scale"]
    if not math.isclose(normal_scale, PBR_NORMAL_SCALE, rel_tol=0.0, abs_tol=1e-12):
        raise PbrMaterialError("PBR normal scale does not match canonical v3")

    roughness_min = values["roughness_min"]
    roughness_max = values["roughness_max"]
    roughness_mean = values["roughness_mean"]
    if not (
        PBR_ROUGHNESS_MIN <= roughness_min <= roughness_mean <= roughness_max <= PBR_ROUGHNESS_MAX
    ):
        raise PbrMaterialError("PBR roughness metrics are outside canonical v3 bounds or order")
    return normal_scale, roughness_min, roughness_max, roughness_mean


def refine_glb_pbr(
    avatar_vrm: bytes,
    *,
    normal_png: bytes,
    metallic_roughness_png: bytes,
    metrics: Mapping[str, float | str],
) -> bytes:
    """Add core-glTF PBR maps to a completed BodyRig VRM without touching rig geometry."""

    if not normal_png.startswith(PNG_SIGNATURE) or not metallic_roughness_png.startswith(PNG_SIGNATURE):
        raise PbrMaterialError("derived PBR maps must be PNG")
    normal_scale, roughness_min, roughness_max, roughness_mean = _validate_refinement_metrics(metrics)
    normal_sha = hashlib.sha256(normal_png).hexdigest()
    roughness_sha = hashlib.sha256(metallic_roughness_png).hexdigest()
    if metrics.get("normal_texture_sha256") != normal_sha or metrics.get("metallic_roughness_texture_sha256") != roughness_sha:
        raise PbrMaterialError("derived PBR map hashes do not match metrics")

    document, binary_bytes = _read_glb(avatar_vrm)
    materials = document.get("materials")
    images = document.get("images")
    textures = document.get("textures")
    views = document.get("bufferViews")
    samplers = document.get("samplers")
    if not isinstance(materials, list) or len(materials) != 1 or not isinstance(materials[0], dict):
        raise PbrMaterialError("BodyRig PBR refinement requires exactly one material")
    if not isinstance(images, list) or len(images) < 2 or not isinstance(textures, list) or len(textures) != 1:
        raise PbrMaterialError("BodyRig PBR refinement requires the base texture and thumbnail contract")
    if not isinstance(views, list) or not isinstance(samplers, list) or len(samplers) != 1:
        raise PbrMaterialError("BodyRig PBR refinement buffer/sampler contract mismatch")
    material = materials[0]
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, dict) or pbr.get("baseColorTexture") != {"index": 0}:
        raise PbrMaterialError("BodyRig base-color material contract mismatch")
    if "normalTexture" in material or "metallicRoughnessTexture" in pbr:
        raise PbrMaterialError("BodyRig avatar is already PBR-refined")

    binary = bytearray(binary_bytes)

    def add_image(payload: bytes, name: str) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(payload)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})
        images.append({"name": name, "bufferView": len(views) - 1, "mimeType": "image/png"})
        return len(images) - 1

    normal_source = add_image(normal_png, "BodyRigSourceDerivedNormal")
    roughness_source = add_image(metallic_roughness_png, "BodyRigSourceDerivedMetallicRoughness")
    textures.append({"sampler": 0, "source": normal_source})
    normal_texture = len(textures) - 1
    textures.append({"sampler": 0, "source": roughness_source})
    roughness_texture = len(textures) - 1

    material["normalTexture"] = {"index": normal_texture, "scale": normal_scale}
    pbr["metallicFactor"] = 0.0
    pbr["roughnessFactor"] = 1.0
    pbr["metallicRoughnessTexture"] = {"index": roughness_texture}

    extras = document.setdefault("extras", {})
    if not isinstance(extras, dict):
        raise PbrMaterialError("BodyRig GLB extras contract is invalid")
    bodyrig = extras.setdefault("bodyrig", {})
    if not isinstance(bodyrig, dict) or "materialRefinement" in bodyrig:
        raise PbrMaterialError("BodyRig material refinement extras are invalid or duplicated")
    bodyrig["materialRefinement"] = {
        "method": PBR_METHOD,
        "baseColorTransfer": PBR_COLOR_TRANSFER,
        "normalTextureSha256": normal_sha,
        "metallicRoughnessTextureSha256": roughness_sha,
        "normalScale": normal_scale,
        "roughnessMin": roughness_min,
        "roughnessMax": roughness_max,
        "roughnessMean": roughness_mean,
        "physicalMeasurement": False,
        "sourceDerivedHeuristic": True,
    }
    document["buffers"][0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary))
