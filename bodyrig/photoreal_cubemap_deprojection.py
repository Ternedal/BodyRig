from __future__ import annotations

import math
from typing import Any, Mapping

AUTHORITY_FORMAT = "bodyrig-spherical-v2-projection-authority"
AUTHORITY_VERSION = 1
LAYOUT_3X2 = 0
TARGET_FOV_DEGREES = 110.0
OUTPUT_SIZE = 768


class PhotorealCubemapDeprojectionError(ValueError):
    pass


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealCubemapDeprojectionError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealCubemapDeprojectionError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealCubemapDeprojectionError(f"{label} cannot be negative")
    return result


def _authority(value: Any) -> int:
    if not isinstance(value, Mapping):
        raise PhotorealCubemapDeprojectionError("cubemap projection authority is missing")
    if value.get("format") != AUTHORITY_FORMAT or value.get("version") != AUTHORITY_VERSION:
        raise PhotorealCubemapDeprojectionError("cubemap projection authority format/version mismatch")
    if value.get("projection_type") != "cbmp":
        raise PhotorealCubemapDeprojectionError("projection authority is not cubemap")
    if value.get("deprojection_authority") is not False:
        raise PhotorealCubemapDeprojectionError("upstream cubemap authority crossed deprojection authority")
    layout = _nonnegative_int(value.get("cubemap_layout"), label="cubemap layout")
    if layout != LAYOUT_3X2:
        raise PhotorealCubemapDeprojectionError(f"unsupported Spherical V2 cubemap layout: {layout}")
    return _nonnegative_int(value.get("cubemap_padding_pixels"), label="cubemap padding")


def build_cubemap_viewports() -> list[dict[str, float | str]]:
    # Six overlapping tangent views cover the full sphere. These are measurement
    # viewports only; their labels do not assert global subject pose authority.
    return [
        {"viewport_id": "front", "yaw_degrees": 0.0, "pitch_degrees": 0.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
        {"viewport_id": "right", "yaw_degrees": 90.0, "pitch_degrees": 0.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
        {"viewport_id": "back", "yaw_degrees": 180.0, "pitch_degrees": 0.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
        {"viewport_id": "left", "yaw_degrees": -90.0, "pitch_degrees": 0.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
        {"viewport_id": "up", "yaw_degrees": 0.0, "pitch_degrees": 90.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
        {"viewport_id": "down", "yaw_degrees": 0.0, "pitch_degrees": -90.0, "horizontal_fov_degrees": TARGET_FOV_DEGREES, "vertical_fov_degrees": TARGET_FOV_DEGREES},
    ]


def _viewport_rays(np_module: Any, viewport: Mapping[str, Any], output_size: int) -> tuple[Any, Any, Any]:
    try:
        yaw = math.radians(float(viewport["yaw_degrees"]))
        pitch = math.radians(float(viewport["pitch_degrees"]))
        horizontal_fov = math.radians(float(viewport["horizontal_fov_degrees"]))
        vertical_fov = math.radians(float(viewport["vertical_fov_degrees"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PhotorealCubemapDeprojectionError("cubemap viewport is invalid") from exc
    if not all(math.isfinite(value) for value in (yaw, pitch, horizontal_fov, vertical_fov)):
        raise PhotorealCubemapDeprojectionError("cubemap viewport contains non-finite values")
    if not 0.0 < horizontal_fov < math.pi or not 0.0 < vertical_fov < math.pi:
        raise PhotorealCubemapDeprojectionError("cubemap viewport FOV is invalid")

    coordinates = (np_module.arange(output_size, dtype=np_module.float64) + 0.5) / output_size
    normalized = coordinates * 2.0 - 1.0
    xx, yy_down = np_module.meshgrid(normalized, normalized)
    camera_x = xx * math.tan(horizontal_fov * 0.5)
    camera_y = -yy_down * math.tan(vertical_fov * 0.5)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = (cp * sy, sp, -cp * cy)
    right = (cy, 0.0, sy)
    up = (-sp * sy, cp, sp * cy)

    ray_x = forward[0] + camera_x * right[0] + camera_y * up[0]
    ray_y = forward[1] + camera_x * right[1] + camera_y * up[1]
    ray_z = forward[2] + camera_x * right[2] + camera_y * up[2]
    norm = np_module.sqrt(ray_x * ray_x + ray_y * ray_y + ray_z * ray_z)
    return ray_x / norm, ray_y / norm, ray_z / norm


def build_cubemap_remap(
    np_module: Any,
    *,
    image_width: int,
    image_height: int,
    projection_authority: Mapping[str, Any],
    viewport: Mapping[str, Any],
    output_size: int = OUTPUT_SIZE,
) -> tuple[Any, Any]:
    padding = _authority(projection_authority)
    if isinstance(image_width, bool) or isinstance(image_height, bool) or image_width < 6 or image_height < 4:
        raise PhotorealCubemapDeprojectionError("cubemap image dimensions are invalid")
    if isinstance(output_size, bool) or not 64 <= output_size <= 2048:
        raise PhotorealCubemapDeprojectionError("cubemap viewport output size is invalid")

    face_width = image_width / 3.0
    face_height = image_height / 2.0
    scale_x = 1.0 - float(padding) / face_width
    scale_y = 1.0 - float(padding) / face_height
    if not 0.0 < scale_x <= 1.0 or not 0.0 < scale_y <= 1.0:
        raise PhotorealCubemapDeprojectionError("cubemap padding consumes a complete cube face")

    x, y, z = _viewport_rays(np_module, viewport, output_size)
    abs_x = np_module.abs(x)
    abs_y = np_module.abs(y)
    abs_z = np_module.abs(z)

    # V2 layout 0 stores: row 0 = right, left, up; row 1 = down, front, back.
    # Equatorial faces match FFmpeg v360's rludfb convention after converting
    # BodyRig's +Y-up/-Z-forward rays to FFmpeg's +Y-down/+Z-forward convention.
    # Spherical Video V2 additionally specifies up-face top=forward and down-face
    # top=back, which is a 180-degree local rotation of FFmpeg's default pole
    # faces; those rotations are applied explicitly below.
    face = np_module.full(x.shape, -1, dtype=np_module.int8)
    uf = np_module.zeros(x.shape, dtype=np_module.float64)
    vf = np_module.zeros(x.shape, dtype=np_module.float64)

    x_major = (abs_x >= abs_y) & (abs_x >= abs_z)
    y_major = (~x_major) & (abs_y >= abs_z)
    z_major = ~(x_major | y_major)

    right = x_major & (x >= 0.0)
    left = x_major & (x < 0.0)
    up = y_major & (y >= 0.0)
    down = y_major & (y < 0.0)
    front = z_major & (z <= 0.0)
    back = z_major & (z > 0.0)

    face[right] = 0
    uf[right] = z[right] / x[right]
    vf[right] = -y[right] / x[right]

    face[left] = 1
    uf[left] = z[left] / x[left]
    vf[left] = y[left] / x[left]

    face[up] = 2
    uf[up] = -x[up] / y[up]
    vf[up] = z[up] / y[up]

    face[down] = 3
    uf[down] = x[down] / y[down]
    vf[down] = z[down] / y[down]

    face[front] = 4
    uf[front] = -x[front] / z[front]
    vf[front] = y[front] / z[front]

    face[back] = 5
    uf[back] = -x[back] / z[back]
    vf[back] = -y[back] / z[back]

    if bool(np_module.any(face < 0)):
        raise PhotorealCubemapDeprojectionError("cubemap ray could not be assigned to a cube face")
    uf = np_module.clip(uf * scale_x, -1.0, 1.0)
    vf = np_module.clip(vf * scale_y, -1.0, 1.0)

    map_x = np_module.empty(x.shape, dtype=np_module.float32)
    map_y = np_module.empty(x.shape, dtype=np_module.float32)
    for face_index in range(6):
        mask = face == face_index
        if not bool(np_module.any(mask)):
            continue
        column = face_index % 3
        row = face_index // 3
        x0 = int(math.ceil(face_width * column))
        x1 = int(math.ceil(face_width * (column + 1)))
        y0 = int(math.ceil(face_height * row))
        y1 = int(math.ceil(face_height * (row + 1)))
        cell_width = x1 - x0
        cell_height = y1 - y0
        if cell_width < 2 or cell_height < 2:
            raise PhotorealCubemapDeprojectionError("cubemap face cell is too small")
        local_x = 0.5 * cell_width * (uf[mask] + 1.0) - 0.5
        local_y = 0.5 * cell_height * (vf[mask] + 1.0) - 0.5
        # Keep OpenCV's bilinear kernel inside the selected atlas cell. V2 padding
        # already moves real samples inward when present; this half-pixel clamp is
        # only a seam-safety bound when padding is zero.
        local_x = np_module.clip(local_x, 0.0, cell_width - 1.001)
        local_y = np_module.clip(local_y, 0.0, cell_height - 1.001)
        map_x[mask] = (x0 + local_x).astype(np_module.float32)
        map_y[mask] = (y0 + local_y).astype(np_module.float32)

    return map_x, map_y


def deproject_cubemap_views(
    runtime: Any,
    image: Any,
    projection_authority: Mapping[str, Any],
    *,
    output_size: int = OUTPUT_SIZE,
) -> list[tuple[str, Any]]:
    if getattr(image, "ndim", None) != 3 or image.shape[0] < 4 or image.shape[1] < 6:
        raise PhotorealCubemapDeprojectionError("cubemap decoded image is invalid")
    height, width = image.shape[:2]
    result: list[tuple[str, Any]] = []
    for viewport in build_cubemap_viewports():
        map_x, map_y = build_cubemap_remap(
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
            raise PhotorealCubemapDeprojectionError("cubemap deprojection produced an empty viewport")
        result.append((str(viewport["viewport_id"]), runtime.np.ascontiguousarray(deprojected)))
    return result
