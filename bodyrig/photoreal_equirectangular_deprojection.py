from __future__ import annotations

import math
from typing import Any, Mapping

AUTHORITY_FORMAT = "bodyrig-spherical-v2-projection-authority"
AUTHORITY_VERSION = 1
TARGET_FOV_DEGREES = 110.0
VIEWPORT_OVERLAP_FRACTION = 0.10
MAX_VIEWPORTS = 8
OUTPUT_SIZE = 768


class PhotorealEquirectangularDeprojectionError(ValueError):
    pass


def _number(value: Any, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise PhotorealEquirectangularDeprojectionError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealEquirectangularDeprojectionError(f"{label} is invalid") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PhotorealEquirectangularDeprojectionError(f"{label} is outside its valid range")
    return result


def _authority(value: Any) -> tuple[dict[str, float], dict[str, float]]:
    if not isinstance(value, Mapping):
        raise PhotorealEquirectangularDeprojectionError("equirectangular projection authority is missing")
    if value.get("format") != AUTHORITY_FORMAT or value.get("version") != AUTHORITY_VERSION:
        raise PhotorealEquirectangularDeprojectionError("equirectangular projection authority format/version mismatch")
    if value.get("projection_type") != "equi":
        raise PhotorealEquirectangularDeprojectionError("projection authority is not equirectangular")
    if value.get("deprojection_authority") is not False:
        raise PhotorealEquirectangularDeprojectionError("upstream projection authority crossed deprojection authority")

    raw_pose = value.get("pose_degrees")
    if not isinstance(raw_pose, Mapping):
        raise PhotorealEquirectangularDeprojectionError("equirectangular projection pose is missing")
    pose = {
        "yaw": _number(raw_pose.get("yaw"), label="projection yaw", minimum=-180.0, maximum=180.0),
        "pitch": _number(raw_pose.get("pitch"), label="projection pitch", minimum=-90.0, maximum=90.0),
        "roll": _number(raw_pose.get("roll"), label="projection roll", minimum=-180.0, maximum=180.0),
    }

    raw_bounds = value.get("equirectangular_bounds_fraction")
    if not isinstance(raw_bounds, Mapping):
        raise PhotorealEquirectangularDeprojectionError("equirectangular bounds are missing")
    bounds = {
        name: _number(raw_bounds.get(name), label=f"equirectangular {name} bound", minimum=0.0, maximum=1.0)
        for name in ("top", "bottom", "left", "right")
    }
    if bounds["top"] + bounds["bottom"] >= 1.0 or bounds["left"] + bounds["right"] >= 1.0:
        raise PhotorealEquirectangularDeprojectionError("equirectangular bounds describe an empty projection")
    return pose, bounds


def _centers(low: float, high: float, fov: float) -> list[float]:
    span = high - low
    if not math.isfinite(span) or span <= 0.0:
        raise PhotorealEquirectangularDeprojectionError("equirectangular angular span is invalid")
    if span <= fov + 1e-9:
        return [round((low + high) * 0.5, 6)]
    preferred_stride = fov * (1.0 - VIEWPORT_OVERLAP_FRACTION)
    count = int(math.ceil((span - fov) / preferred_stride)) + 1
    stride = (span - fov) / (count - 1)
    first = low + fov * 0.5
    return [round(first + index * stride, 6) for index in range(count)]


def build_equirectangular_viewports(projection_authority: Mapping[str, Any]) -> list[dict[str, float | str]]:
    _pose, bounds = _authority(projection_authority)
    yaw_low = -180.0 + 360.0 * bounds["left"]
    yaw_high = 180.0 - 360.0 * bounds["right"]
    pitch_low = -90.0 + 180.0 * bounds["bottom"]
    pitch_high = 90.0 - 180.0 * bounds["top"]
    horizontal_span = yaw_high - yaw_low
    vertical_span = pitch_high - pitch_low
    horizontal_fov = min(TARGET_FOV_DEGREES, horizontal_span)
    vertical_fov = min(TARGET_FOV_DEGREES, vertical_span)
    yaws = _centers(yaw_low, yaw_high, horizontal_fov)
    pitches = _centers(pitch_low, pitch_high, vertical_fov)
    if len(yaws) * len(pitches) > MAX_VIEWPORTS:
        raise PhotorealEquirectangularDeprojectionError(
            f"equirectangular viewport grid exceeds safety bound {MAX_VIEWPORTS}"
        )
    result: list[dict[str, float | str]] = []
    index = 0
    for pitch in pitches:
        for yaw in yaws:
            result.append(
                {
                    "viewport_id": f"v{index:02d}",
                    "yaw_degrees": yaw,
                    "pitch_degrees": pitch,
                    "horizontal_fov_degrees": round(horizontal_fov, 6),
                    "vertical_fov_degrees": round(vertical_fov, 6),
                }
            )
            index += 1
    return result


def build_equirectangular_remap(
    np_module: Any,
    *,
    image_width: int,
    image_height: int,
    projection_authority: Mapping[str, Any],
    viewport: Mapping[str, Any],
    output_size: int = OUTPUT_SIZE,
) -> tuple[Any, Any]:
    _pose, bounds = _authority(projection_authority)
    if isinstance(image_width, bool) or isinstance(image_height, bool) or image_width < 2 or image_height < 2:
        raise PhotorealEquirectangularDeprojectionError("equirectangular image dimensions are invalid")
    if isinstance(output_size, bool) or not 64 <= output_size <= 2048:
        raise PhotorealEquirectangularDeprojectionError("equirectangular viewport output size is invalid")

    yaw = math.radians(_number(viewport.get("yaw_degrees"), label="viewport yaw", minimum=-180.0, maximum=180.0))
    pitch = math.radians(_number(viewport.get("pitch_degrees"), label="viewport pitch", minimum=-90.0, maximum=90.0))
    hfov = math.radians(_number(viewport.get("horizontal_fov_degrees"), label="viewport horizontal FOV", minimum=1e-6, maximum=179.0))
    vfov = math.radians(_number(viewport.get("vertical_fov_degrees"), label="viewport vertical FOV", minimum=1e-6, maximum=179.0))

    coordinates = (np_module.arange(output_size, dtype=np_module.float64) + 0.5) / output_size
    normalized = coordinates * 2.0 - 1.0
    xx, yy_down = np_module.meshgrid(normalized, normalized)
    camera_x = xx * math.tan(hfov * 0.5)
    camera_y = -yy_down * math.tan(vfov * 0.5)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = (cp * sy, sp, -cp * cy)
    right = (cy, 0.0, sy)
    up = (-sp * sy, cp, sp * cy)

    ray_x = forward[0] + camera_x * right[0] + camera_y * up[0]
    ray_y = forward[1] + camera_x * right[1] + camera_y * up[1]
    ray_z = forward[2] + camera_x * right[2] + camera_y * up[2]
    norm = np_module.sqrt(ray_x * ray_x + ray_y * ray_y + ray_z * ray_z)
    ray_x /= norm
    ray_y /= norm
    ray_z /= norm

    source_yaw = np_module.arctan2(ray_x, -ray_z)
    source_pitch = np_module.arcsin(np_module.clip(ray_y, -1.0, 1.0))
    u_full = np_module.mod(source_yaw / (2.0 * math.pi) + 0.5, 1.0)
    v_full = 0.5 - source_pitch / math.pi

    horizontal_span = 1.0 - bounds["left"] - bounds["right"]
    vertical_span = 1.0 - bounds["top"] - bounds["bottom"]
    if horizontal_span >= 1.0 - 1e-12:
        u_crop = u_full
        valid_u = np_module.ones_like(u_full, dtype=bool)
    else:
        u_crop = (u_full - bounds["left"]) / horizontal_span
        valid_u = (u_full >= bounds["left"]) & (u_full <= 1.0 - bounds["right"])
    v_crop = (v_full - bounds["top"]) / vertical_span
    valid_v = (v_full >= bounds["top"]) & (v_full <= 1.0 - bounds["bottom"])
    valid = valid_u & valid_v

    map_x = (u_crop * (image_width - 1)).astype(np_module.float32)
    map_y = (v_crop * (image_height - 1)).astype(np_module.float32)
    map_x = np_module.where(valid, map_x, -1.0).astype(np_module.float32)
    map_y = np_module.where(valid, map_y, -1.0).astype(np_module.float32)
    return map_x, map_y


def deproject_equirectangular_views(
    runtime: Any,
    image: Any,
    projection_authority: Mapping[str, Any],
    *,
    output_size: int = OUTPUT_SIZE,
) -> list[tuple[str, Any]]:
    if getattr(image, "ndim", None) != 3 or image.shape[0] < 2 or image.shape[1] < 2:
        raise PhotorealEquirectangularDeprojectionError("equirectangular decoded image is invalid")
    height, width = image.shape[:2]
    result: list[tuple[str, Any]] = []
    for viewport in build_equirectangular_viewports(projection_authority):
        map_x, map_y = build_equirectangular_remap(
            runtime.np,
            image_width=width,
            image_height=height,
            projection_authority=projection_authority,
            viewport=viewport,
            output_size=output_size,
        )
        deprojected = runtime.cv2.remap(
            image,
            map_x,
            map_y,
            interpolation=runtime.cv2.INTER_LINEAR,
            borderMode=runtime.cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        if deprojected is None or deprojected.size == 0:
            raise PhotorealEquirectangularDeprojectionError("equirectangular deprojection produced an empty viewport")
        result.append((str(viewport["viewport_id"]), runtime.np.ascontiguousarray(deprojected)))
    return result
