from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from .photoreal_mesh_projection import (
    PhotorealMeshProjectionError,
    parse_mesh_projection_file,
)

AUTHORITY_FORMAT = "bodyrig-spherical-v2-projection-authority"
AUTHORITY_VERSION = 1
TARGET_FOV_DEGREES = 110.0
VIEWPORT_OVERLAP_FRACTION = 0.10
MAX_VIEWPORTS = 8
OUTPUT_SIZE = 768
NEAR_DEPTH = 1e-4
MIN_VIEWPORT_COVERAGE = 0.10


class PhotorealMeshDeprojectionError(ValueError):
    pass


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealMeshDeprojectionError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealMeshDeprojectionError(f"{label} is invalid") from exc
    if result < 1:
        raise PhotorealMeshDeprojectionError(f"{label} must be positive")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealMeshDeprojectionError(f"{label} is invalid")
    return result


def _authority(value: Any, geometry: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise PhotorealMeshDeprojectionError("mesh projection authority is missing")
    if value.get("format") != AUTHORITY_FORMAT or value.get("version") != AUTHORITY_VERSION:
        raise PhotorealMeshDeprojectionError("mesh projection authority format/version mismatch")
    if value.get("projection_type") != "mshp":
        raise PhotorealMeshDeprojectionError("projection authority is not mesh")
    if value.get("deprojection_authority") is not False:
        raise PhotorealMeshDeprojectionError("upstream mesh authority crossed deprojection authority")
    if geometry.get("format") != "bodyrig-spherical-v2-mesh-geometry" or geometry.get("version") != 1:
        raise PhotorealMeshDeprojectionError("mesh geometry format/version mismatch")
    if geometry.get("materialized") is not True:
        raise PhotorealMeshDeprojectionError("mesh geometry is not materialized")
    if geometry.get("render_authority") is not False or geometry.get("production_activation") is not False:
        raise PhotorealMeshDeprojectionError("mesh geometry crossed its authority boundary")

    checks = (
        ("mesh_projection_geometry_sha256", "decompressed_payload_sha256"),
        ("mesh_projection_mesh_count", "mesh_count"),
        ("mesh_projection_total_vertex_count", "total_vertex_count"),
        ("mesh_projection_total_index_count", "total_index_count"),
        ("mesh_projection_texture_ids", "texture_ids"),
        ("mesh_projection_index_types", "index_types"),
        ("mesh_projection_unknown_box_types", "unknown_box_types"),
        ("mesh_projection_encoding", "encoding"),
        ("mesh_projection_payload_bytes", "encoded_payload_bytes"),
        ("mesh_projection_crc32", "mesh_projection_crc32"),
    )
    for authority_field, geometry_field in checks:
        expected = value.get(authority_field)
        observed = geometry.get(geometry_field)
        if isinstance(expected, list) and isinstance(observed, list):
            if sorted(expected) != sorted(observed):
                raise PhotorealMeshDeprojectionError(
                    f"mesh geometry disagrees with projection authority: {authority_field}"
                )
        elif expected != observed:
            raise PhotorealMeshDeprojectionError(
                f"mesh geometry disagrees with projection authority: {authority_field}"
            )
    _sha(value.get("mesh_projection_geometry_sha256"), label="mesh geometry SHA-256")
    if _positive_int(value.get("mesh_projection_mesh_count"), label="mesh count") > 2:
        raise PhotorealMeshDeprojectionError("mesh count exceeds v2 maximum")


def load_mesh_projection_geometry(
    source_path: str | Path,
    projection_authority: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        geometry = parse_mesh_projection_file(source_path, materialize=True)
    except (OSError, PhotorealMeshProjectionError) as exc:
        raise PhotorealMeshDeprojectionError(f"mesh geometry could not be read: {exc}") from exc
    _authority(projection_authority, geometry)
    return geometry


def _triangles(mesh: Mapping[str, Any]) -> list[tuple[int, int, int]]:
    vertices = mesh.get("vertices")
    lists = mesh.get("vertex_lists")
    if not isinstance(vertices, list) or not vertices:
        raise PhotorealMeshDeprojectionError("mesh contains no materialized vertices")
    if not isinstance(lists, list) or not lists:
        raise PhotorealMeshDeprojectionError("mesh contains no materialized vertex lists")
    result: list[tuple[int, int, int]] = []
    for list_index, raw in enumerate(lists):
        if not isinstance(raw, Mapping):
            raise PhotorealMeshDeprojectionError("mesh vertex list is invalid")
        texture_id = raw.get("texture_id")
        index_type = raw.get("index_type")
        indices = raw.get("indices")
        if isinstance(texture_id, bool) or not isinstance(texture_id, int) or not 0 <= texture_id <= 255:
            raise PhotorealMeshDeprojectionError("mesh texture ID is invalid")
        if texture_id != 0:
            continue
        if index_type not in {0, 1, 2} or not isinstance(indices, list):
            raise PhotorealMeshDeprojectionError("mesh primitive list is invalid")
        if any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < len(vertices) for item in indices):
            raise PhotorealMeshDeprojectionError("mesh primitive references an invalid vertex")
        if index_type == 0:
            if len(indices) % 3 != 0:
                raise PhotorealMeshDeprojectionError(
                    f"mesh triangle list {list_index} index count is not divisible by three"
                )
            result.extend(tuple(indices[offset : offset + 3]) for offset in range(0, len(indices), 3))
        elif index_type == 1:
            for offset in range(max(0, len(indices) - 2)):
                triangle = (
                    (indices[offset], indices[offset + 1], indices[offset + 2])
                    if offset % 2 == 0
                    else (indices[offset + 1], indices[offset], indices[offset + 2])
                )
                if len(set(triangle)) == 3:
                    result.append(triangle)
        else:
            for offset in range(1, max(1, len(indices) - 1)):
                triangle = (indices[0], indices[offset], indices[offset + 1])
                if len(set(triangle)) == 3:
                    result.append(triangle)
    if not result:
        raise PhotorealMeshDeprojectionError("mesh contains no video-texture triangles")
    return result


def _selected_mesh(geometry: Mapping[str, Any], eye: str) -> Mapping[str, Any]:
    meshes = geometry.get("meshes")
    if not isinstance(meshes, list) or not 1 <= len(meshes) <= 2:
        raise PhotorealMeshDeprojectionError("mesh geometry must contain one or two meshes")
    if len(meshes) == 1:
        if eye not in {"mono", "left", "right"}:
            raise PhotorealMeshDeprojectionError("mesh eye is invalid")
        mesh = meshes[0]
    else:
        if eye == "left":
            mesh = meshes[0]
        elif eye == "right":
            mesh = meshes[1]
        else:
            raise PhotorealMeshDeprojectionError("two-mesh projection requires a left or right eye sample")
    if not isinstance(mesh, Mapping):
        raise PhotorealMeshDeprojectionError("selected mesh is invalid")
    return mesh


def _video_vertices(mesh: Mapping[str, Any]) -> list[tuple[float, float, float, float, float]]:
    vertices = mesh.get("vertices")
    if not isinstance(vertices, list) or not vertices:
        raise PhotorealMeshDeprojectionError("mesh contains no materialized vertices")
    referenced: set[int] = set()
    lists = mesh.get("vertex_lists")
    if not isinstance(lists, list):
        raise PhotorealMeshDeprojectionError("mesh vertex lists are missing")
    for raw in lists:
        if not isinstance(raw, Mapping) or raw.get("texture_id") != 0:
            continue
        indices = raw.get("indices")
        if isinstance(indices, list):
            referenced.update(item for item in indices if isinstance(item, int) and not isinstance(item, bool))
    result: list[tuple[float, float, float, float, float]] = []
    for index in sorted(referenced):
        if not 0 <= index < len(vertices):
            raise PhotorealMeshDeprojectionError("mesh video texture references an invalid vertex")
        raw = vertices[index]
        if not isinstance(raw, (list, tuple)) or len(raw) != 5:
            raise PhotorealMeshDeprojectionError("mesh vertex is invalid")
        try:
            values = tuple(float(item) for item in raw)
        except (TypeError, ValueError) as exc:
            raise PhotorealMeshDeprojectionError("mesh vertex is invalid") from exc
        if any(not math.isfinite(item) for item in values):
            raise PhotorealMeshDeprojectionError("mesh vertex contains non-finite values")
        x, y, z, u, v = values
        if x * x + y * y + z * z <= 1e-18:
            raise PhotorealMeshDeprojectionError("mesh vertex direction has zero length")
        if not -1e-6 <= u <= 1.0 + 1e-6 or not -1e-6 <= v <= 1.0 + 1e-6:
            raise PhotorealMeshDeprojectionError("mesh video texture coordinate is outside normalized range")
        result.append(values)
    if not result:
        raise PhotorealMeshDeprojectionError("mesh has no vertices backed by video texture 0")
    return result


def _circular_yaw_interval(yaws: list[float]) -> tuple[float, float]:
    values = sorted((value % 360.0) for value in yaws)
    if len(values) == 1:
        return values[0], values[0]
    largest_gap = -1.0
    largest_index = 0
    for index, value in enumerate(values):
        following = values[(index + 1) % len(values)] + (360.0 if index == len(values) - 1 else 0.0)
        gap = following - value
        if gap > largest_gap:
            largest_gap = gap
            largest_index = index
    start = values[(largest_index + 1) % len(values)]
    unwrapped = [value if value >= start else value + 360.0 for value in values]
    return min(unwrapped), max(unwrapped)


def _centers(low: float, high: float, fov: float) -> list[float]:
    span = high - low
    if not math.isfinite(span) or span < 0.0:
        raise PhotorealMeshDeprojectionError("mesh angular span is invalid")
    if span <= fov + 1e-9:
        return [(low + high) * 0.5]
    preferred_stride = fov * (1.0 - VIEWPORT_OVERLAP_FRACTION)
    count = int(math.ceil((span - fov) / preferred_stride)) + 1
    stride = (span - fov) / (count - 1)
    first = low + fov * 0.5
    return [first + index * stride for index in range(count)]


def build_mesh_viewports(mesh: Mapping[str, Any]) -> list[dict[str, float | str]]:
    vertices = _video_vertices(mesh)
    yaws: list[float] = []
    pitches: list[float] = []
    for x, y, z, _u, _v in vertices:
        norm = math.sqrt(x * x + y * y + z * z)
        x /= norm
        y /= norm
        z /= norm
        yaws.append(math.degrees(math.atan2(x, -z)))
        pitches.append(math.degrees(math.asin(max(-1.0, min(1.0, y)))))
    yaw_low, yaw_high = _circular_yaw_interval(yaws)
    pitch_low, pitch_high = min(pitches), max(pitches)
    horizontal_span = max(1e-6, yaw_high - yaw_low)
    vertical_span = max(1e-6, pitch_high - pitch_low)
    horizontal_fov = min(TARGET_FOV_DEGREES, horizontal_span)
    vertical_fov = min(TARGET_FOV_DEGREES, vertical_span)
    yaw_centers = _centers(yaw_low, yaw_high, horizontal_fov)
    pitch_centers = _centers(pitch_low, pitch_high, vertical_fov)
    if len(yaw_centers) * len(pitch_centers) > MAX_VIEWPORTS:
        raise PhotorealMeshDeprojectionError(
            f"mesh viewport grid exceeds safety bound {MAX_VIEWPORTS}"
        )
    result: list[dict[str, float | str]] = []
    index = 0
    for pitch in pitch_centers:
        for yaw in yaw_centers:
            normalized_yaw = ((yaw + 180.0) % 360.0) - 180.0
            result.append(
                {
                    "viewport_id": f"v{index:02d}",
                    "yaw_degrees": round(normalized_yaw, 6),
                    "pitch_degrees": round(pitch, 6),
                    "horizontal_fov_degrees": round(horizontal_fov, 6),
                    "vertical_fov_degrees": round(vertical_fov, 6),
                }
            )
            index += 1
    return result


def _triangulated_clipped_polygon(
    vertices: list[tuple[float, float, float, float, float]],
) -> list[tuple[tuple[float, float, float, float, float], tuple[float, float, float, float, float], tuple[float, float, float, float, float]]]:
    if len(vertices) != 3:
        raise PhotorealMeshDeprojectionError("mesh triangle vertex count is invalid")
    output: list[tuple[float, float, float, float, float]] = []
    previous = vertices[-1]
    previous_inside = previous[2] >= NEAR_DEPTH
    for current in vertices:
        current_inside = current[2] >= NEAR_DEPTH
        if current_inside != previous_inside:
            denominator = current[2] - previous[2]
            if abs(denominator) <= 1e-18:
                raise PhotorealMeshDeprojectionError("mesh near-plane intersection is unstable")
            amount = (NEAR_DEPTH - previous[2]) / denominator
            output.append(
                tuple(previous[field] + amount * (current[field] - previous[field]) for field in range(5))
            )
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    if len(output) < 3:
        return []
    return [(output[0], output[index], output[index + 1]) for index in range(1, len(output) - 1)]


def build_mesh_remap(
    np_module: Any,
    *,
    image_width: int,
    image_height: int,
    mesh: Mapping[str, Any],
    viewport: Mapping[str, Any],
    output_size: int = OUTPUT_SIZE,
) -> tuple[Any, Any, float]:
    if isinstance(image_width, bool) or isinstance(image_height, bool) or image_width < 2 or image_height < 2:
        raise PhotorealMeshDeprojectionError("mesh source image dimensions are invalid")
    if isinstance(output_size, bool) or not 64 <= output_size <= 2048:
        raise PhotorealMeshDeprojectionError("mesh viewport output size is invalid")
    try:
        yaw = math.radians(float(viewport["yaw_degrees"]))
        pitch = math.radians(float(viewport["pitch_degrees"]))
        horizontal_fov = math.radians(float(viewport["horizontal_fov_degrees"]))
        vertical_fov = math.radians(float(viewport["vertical_fov_degrees"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PhotorealMeshDeprojectionError("mesh viewport is invalid") from exc
    if not all(math.isfinite(value) for value in (yaw, pitch, horizontal_fov, vertical_fov)):
        raise PhotorealMeshDeprojectionError("mesh viewport contains non-finite values")
    if not 0.0 < horizontal_fov < math.pi or not 0.0 < vertical_fov < math.pi:
        raise PhotorealMeshDeprojectionError("mesh viewport FOV is invalid")

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = (cp * sy, sp, -cp * cy)
    right = (cy, 0.0, sy)
    up = (-sp * sy, cp, sp * cy)
    tangent_x = math.tan(horizontal_fov * 0.5)
    tangent_y = math.tan(vertical_fov * 0.5)

    map_x = np_module.full((output_size, output_size), -1.0, dtype=np_module.float32)
    map_y = np_module.full((output_size, output_size), -1.0, dtype=np_module.float32)
    depth_buffer = np_module.full((output_size, output_size), np_module.inf, dtype=np_module.float64)
    vertices = mesh.get("vertices")
    if not isinstance(vertices, list):
        raise PhotorealMeshDeprojectionError("mesh vertices are missing")

    for indices in _triangles(mesh):
        transformed: list[tuple[float, float, float, float, float]] = []
        for vertex_index in indices:
            raw = vertices[vertex_index]
            if not isinstance(raw, (list, tuple)) or len(raw) != 5:
                raise PhotorealMeshDeprojectionError("mesh triangle vertex is invalid")
            x, y, z, u, v = (float(item) for item in raw)
            norm = math.sqrt(x * x + y * y + z * z)
            if not math.isfinite(norm) or norm <= 1e-9:
                raise PhotorealMeshDeprojectionError("mesh triangle direction is invalid")
            x, y, z = x / norm, y / norm, z / norm
            camera_x = x * right[0] + y * right[1] + z * right[2]
            camera_y = x * up[0] + y * up[1] + z * up[2]
            camera_depth = x * forward[0] + y * forward[1] + z * forward[2]
            transformed.append((camera_x, camera_y, camera_depth, u, v))

        for triangle in _triangulated_clipped_polygon(transformed):
            projected: list[tuple[float, float, float, float, float]] = []
            for camera_x, camera_y, camera_depth, u, v in triangle:
                screen_x = ((camera_x / camera_depth) / tangent_x * 0.5 + 0.5) * (output_size - 1)
                screen_y = (0.5 - (camera_y / camera_depth) / tangent_y * 0.5) * (output_size - 1)
                projected.append((screen_x, screen_y, camera_depth, u, v))
            x0, y0 = projected[0][0], projected[0][1]
            x1, y1 = projected[1][0], projected[1][1]
            x2, y2 = projected[2][0], projected[2][1]
            denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if not math.isfinite(denominator) or abs(denominator) <= 1e-12:
                continue
            minimum_x = max(0, int(math.floor(min(x0, x1, x2))))
            maximum_x = min(output_size - 1, int(math.ceil(max(x0, x1, x2))))
            minimum_y = max(0, int(math.floor(min(y0, y1, y2))))
            maximum_y = min(output_size - 1, int(math.ceil(max(y0, y1, y2))))
            if minimum_x > maximum_x or minimum_y > maximum_y:
                continue
            xs = np_module.arange(minimum_x, maximum_x + 1, dtype=np_module.float64) + 0.5
            ys = np_module.arange(minimum_y, maximum_y + 1, dtype=np_module.float64) + 0.5
            xx, yy = np_module.meshgrid(xs, ys)
            weight0 = ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) / denominator
            weight1 = ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) / denominator
            weight2 = 1.0 - weight0 - weight1
            inside = (weight0 >= -1e-8) & (weight1 >= -1e-8) & (weight2 >= -1e-8)
            depth0, depth1, depth2 = projected[0][2], projected[1][2], projected[2][2]
            inverse_depth = weight0 / depth0 + weight1 / depth1 + weight2 / depth2
            valid_depth = inverse_depth > 0.0
            safe_inverse_depth = np_module.where(valid_depth, inverse_depth, 1.0)
            depth = np_module.where(valid_depth, 1.0 / safe_inverse_depth, np_module.inf)
            u = (
                weight0 * projected[0][3] / depth0
                + weight1 * projected[1][3] / depth1
                + weight2 * projected[2][3] / depth2
            ) / safe_inverse_depth
            v = (
                weight0 * projected[0][4] / depth0
                + weight1 * projected[1][4] / depth1
                + weight2 * projected[2][4] / depth2
            ) / safe_inverse_depth
            valid_texture = (u >= -1e-6) & (u <= 1.0 + 1e-6) & (v >= -1e-6) & (v <= 1.0 + 1e-6)
            region = (slice(minimum_y, maximum_y + 1), slice(minimum_x, maximum_x + 1))
            existing_depth = depth_buffer[region]
            writable = inside & valid_depth & valid_texture & (depth < existing_depth)
            if not bool(np_module.any(writable)):
                continue
            existing_x = map_x[region]
            existing_y = map_y[region]
            existing_depth[writable] = depth[writable]
            clipped_u = np_module.clip(u, 0.0, 1.0)
            clipped_v = np_module.clip(v, 0.0, 1.0)
            existing_x[writable] = (clipped_u[writable] * (image_width - 1)).astype(np_module.float32)
            existing_y[writable] = ((1.0 - clipped_v[writable]) * (image_height - 1)).astype(np_module.float32)

    coverage = float(np_module.count_nonzero(map_x >= 0.0)) / float(output_size * output_size)
    return map_x, map_y, round(coverage, 6)


def _prepare_remaps(
    np_module: Any,
    geometry: Mapping[str, Any],
    projection_authority: Mapping[str, Any],
    *,
    eye: str,
    image_width: int,
    image_height: int,
    output_size: int,
) -> list[tuple[str, Any, Any, float]]:
    _authority(projection_authority, geometry)
    mesh = _selected_mesh(geometry, eye)
    result: list[tuple[str, Any, Any, float]] = []
    for viewport in build_mesh_viewports(mesh):
        map_x, map_y, coverage = build_mesh_remap(
            np_module,
            image_width=image_width,
            image_height=image_height,
            mesh=mesh,
            viewport=viewport,
            output_size=output_size,
        )
        if coverage >= MIN_VIEWPORT_COVERAGE:
            result.append((str(viewport["viewport_id"]), map_x, map_y, coverage))
    if not result:
        raise PhotorealMeshDeprojectionError("mesh produced no sufficiently covered tangent viewport")
    return result


def deproject_mesh_views(
    runtime: Any,
    image: Any,
    source_path: str | Path,
    projection_authority: Mapping[str, Any],
    *,
    eye: str,
    cache: MutableMapping[Any, Any] | None = None,
    output_size: int = OUTPUT_SIZE,
) -> list[tuple[str, Any]]:
    if getattr(image, "ndim", None) != 3 or image.shape[0] < 2 or image.shape[1] < 2:
        raise PhotorealMeshDeprojectionError("mesh decoded image is invalid")
    source = str(Path(source_path))
    geometry_sha = _sha(
        projection_authority.get("mesh_projection_geometry_sha256"),
        label="mesh geometry SHA-256",
    )
    geometry_key = ("geometry", source, geometry_sha)
    work_cache: MutableMapping[Any, Any] = {} if cache is None else cache
    geometry = work_cache.get(geometry_key)
    if geometry is None:
        geometry = load_mesh_projection_geometry(source, projection_authority)
        work_cache[geometry_key] = geometry
    height, width = image.shape[:2]
    remap_key = ("remaps", source, geometry_sha, eye, int(width), int(height), int(output_size))
    remaps = work_cache.get(remap_key)
    if remaps is None:
        remaps = _prepare_remaps(
            runtime.np,
            geometry,
            projection_authority,
            eye=eye,
            image_width=width,
            image_height=height,
            output_size=output_size,
        )
        work_cache[remap_key] = remaps
    result: list[tuple[str, Any]] = []
    for viewport_id, map_x, map_y, _coverage in remaps:
        deprojected = runtime.cv2.remap(
            image,
            map_x,
            map_y,
            interpolation=runtime.cv2.INTER_LINEAR,
            borderMode=runtime.cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        if deprojected is None or deprojected.size == 0:
            raise PhotorealMeshDeprojectionError("mesh deprojection produced an empty viewport")
        result.append((viewport_id, runtime.np.ascontiguousarray(deprojected)))
    return result
