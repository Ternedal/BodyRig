from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

from .bridges.sith_canonical_texture_bake import (
    bind_canonical_smplx_uvs,
    dilate_texture_gutter,
    load_canonical_smplx_uv_template,
)


MIN_SMPLX_VERTEX_COUNT = 10475
DEFAULT_RESOLUTION = 1024
DEFAULT_GUTTER_PIXELS = 8
QUERY_CHUNK_SIZE = 384
TEACHER_CHUNK_SIZE = 32768


class PhotorealP3TeacherPointBakeError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_exavatar_teacher_points(
    path: str | Path,
    *,
    np: Any,
) -> tuple[Any, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealP3TeacherPointBakeError(
            f"ExAvatar teacher point export is missing/not regular: {source}"
        )

    xyz: list[tuple[float, float, float]] = []
    rgb: list[tuple[float, float, float]] = []
    try:
        with source.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                raw = line.strip()
                if not raw:
                    continue
                parts = raw.split()
                if len(parts) != 6:
                    raise PhotorealP3TeacherPointBakeError(
                        f"ExAvatar teacher point line {line_number} must contain six values"
                    )
                try:
                    values = tuple(float(item) for item in parts)
                except ValueError as exc:
                    raise PhotorealP3TeacherPointBakeError(
                        f"ExAvatar teacher point line {line_number} is not numeric"
                    ) from exc
                if not all(math.isfinite(value) for value in values):
                    raise PhotorealP3TeacherPointBakeError(
                        f"ExAvatar teacher point line {line_number} is non-finite"
                    )
                if any(value < 0.0 or value > 255.0 for value in values[3:]):
                    raise PhotorealP3TeacherPointBakeError(
                        f"ExAvatar teacher RGB line {line_number} is outside 0..255"
                    )
                xyz.append((values[0], values[1], values[2]))
                rgb.append((values[3] / 255.0, values[4] / 255.0, values[5] / 255.0))
    except (OSError, UnicodeError) as exc:
        raise PhotorealP3TeacherPointBakeError(
            f"ExAvatar teacher point export is unreadable: {source}"
        ) from exc

    if len(xyz) < MIN_SMPLX_VERTEX_COUNT:
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher point export is smaller than the canonical SMPL-X surface"
        )

    xyz_arr = np.asarray(xyz, dtype=np.float32)
    rgb_arr = np.asarray(rgb, dtype=np.float32)
    if xyz_arr.shape != (len(xyz), 3) or rgb_arr.shape != (len(rgb), 3):
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher point export has invalid array shape"
        )
    if not bool(np.all(np.isfinite(xyz_arr))) or not bool(np.all(np.isfinite(rgb_arr))):
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher point export contains non-finite values"
        )
    return xyz_arr, rgb_arr


def _validate_teacher_arrays(
    *,
    np: Any,
    teacher_xyz: Any,
    teacher_rgb: Any,
) -> tuple[Any, Any]:
    xyz = np.asarray(teacher_xyz, dtype=np.float32)
    rgb = np.asarray(teacher_rgb, dtype=np.float32)
    if (
        xyz.ndim != 2
        or rgb.ndim != 2
        or xyz.shape[1:] != (3,)
        or rgb.shape[1:] != (3,)
        or xyz.shape[0] != rgb.shape[0]
        or xyz.shape[0] < MIN_SMPLX_VERTEX_COUNT
    ):
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher point arrays have invalid shape/count"
        )
    if not bool(np.all(np.isfinite(xyz))) or not bool(np.all(np.isfinite(rgb))):
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher point arrays contain non-finite values"
        )
    if float(np.min(rgb)) < -1e-6 or float(np.max(rgb)) > 1.000001:
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar teacher RGB is outside normalized 0..1 range"
        )
    return xyz, rgb


def _nearest_teacher_rgb(
    *,
    torch: Any,
    query_points: Any,
    teacher_xyz: Any,
    teacher_rgb: Any,
) -> tuple[Any, Any]:
    if query_points.ndim != 2 or query_points.shape[1] != 3:
        raise PhotorealP3TeacherPointBakeError(
            "canonical UV raster query points have invalid shape"
        )

    rgb_chunks: list[Any] = []
    distance_chunks: list[Any] = []
    with torch.no_grad():
        for query_start in range(0, int(query_points.shape[0]), QUERY_CHUNK_SIZE):
            query = query_points[query_start : query_start + QUERY_CHUNK_SIZE]
            best_distance = torch.full(
                (query.shape[0],),
                float("inf"),
                dtype=torch.float32,
                device=query.device,
            )
            best_rgb = torch.zeros(
                (query.shape[0], 3),
                dtype=torch.float32,
                device=query.device,
            )
            for teacher_start in range(
                0,
                int(teacher_xyz.shape[0]),
                TEACHER_CHUNK_SIZE,
            ):
                xyz = teacher_xyz[
                    teacher_start : teacher_start + TEACHER_CHUNK_SIZE
                ]
                rgb = teacher_rgb[
                    teacher_start : teacher_start + TEACHER_CHUNK_SIZE
                ]
                distances = torch.cdist(query[None], xyz[None]).squeeze(0)
                local_distance, local_index = torch.min(distances, dim=1)
                improve = local_distance < best_distance
                if bool(torch.any(improve).item()):
                    best_distance[improve] = local_distance[improve]
                    best_rgb[improve] = rgb[local_index[improve]]
            if not bool(torch.all(torch.isfinite(best_distance)).item()):
                raise PhotorealP3TeacherPointBakeError(
                    "teacher-to-student nearest color transfer is non-finite"
                )
            rgb_chunks.append(best_rgb.detach().cpu())
            distance_chunks.append(best_distance.detach().cpu())

    return torch.cat(rgb_chunks, dim=0), torch.cat(distance_chunks, dim=0)


def bake_exavatar_teacher_points_to_canonical_smplx(
    *,
    torch: Any,
    np: Any,
    donor_positions: Any,
    donor_faces: Iterable[Sequence[int]],
    canonical_uv_template: str | Path,
    teacher_xyz: Any,
    teacher_rgb: Any,
    device: Any,
    resolution: int = DEFAULT_RESOLUTION,
    gutter_pixels: int = DEFAULT_GUTTER_PIXELS,
) -> tuple[
    list[tuple[float, float]],
    list[list[tuple[int, int]]],
    bytes,
    dict[str, float | str],
]:
    try:
        import nvdiffrast.torch as dr
        from PIL import Image
    except ImportError as exc:
        raise PhotorealP3TeacherPointBakeError(
            f"teacher-point UV bake dependencies are unavailable: {exc}"
        ) from exc

    if (
        isinstance(resolution, bool)
        or not isinstance(resolution, int)
        or resolution < 256
        or resolution > 4096
    ):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point UV bake resolution is invalid"
        )
    if (
        isinstance(gutter_pixels, bool)
        or not isinstance(gutter_pixels, int)
        or gutter_pixels < 0
        or gutter_pixels > 64
    ):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point UV bake gutter is invalid"
        )

    template = Path(canonical_uv_template).expanduser().resolve()
    if not template.is_file() or template.is_symlink():
        raise PhotorealP3TeacherPointBakeError(
            f"canonical SMPL-X UV template is missing/not regular: {template}"
        )

    xyz_np, rgb_np = _validate_teacher_arrays(
        np=np,
        teacher_xyz=teacher_xyz,
        teacher_rgb=teacher_rgb,
    )

    donor = donor_positions
    if not hasattr(donor, "shape"):
        donor = torch.tensor(donor_positions, dtype=torch.float32, device=device)
    else:
        donor = donor.to(device=device, dtype=torch.float32)
    if donor.ndim != 2 or tuple(donor.shape[1:]) != (3,):
        raise PhotorealP3TeacherPointBakeError(
            "ExAvatar donor mesh positions have invalid shape"
        )

    (
        canonical_vertex_count,
        texcoords,
        geometry_faces,
        texture_faces,
    ) = load_canonical_smplx_uv_template(template)
    bound_faces = bind_canonical_smplx_uvs(
        donor_vertex_count=int(donor.shape[0]),
        donor_faces=donor_faces,
        canonical_vertex_count=canonical_vertex_count,
        canonical_texcoords=texcoords,
        canonical_geometry_faces=geometry_faces,
        canonical_texture_faces=texture_faces,
    )

    uv = torch.tensor(texcoords, dtype=torch.float32, device=device)
    uv_clip = (
        uv * torch.tensor([2.0, -2.0], dtype=torch.float32, device=device)
        + torch.tensor([-1.0, 1.0], dtype=torch.float32, device=device)
    )
    uv_clip4 = torch.cat(
        (
            uv_clip,
            torch.zeros_like(uv_clip[:, :1]),
            torch.ones_like(uv_clip[:, :1]),
        ),
        dim=1,
    )
    texture_face_tensor = torch.tensor(
        texture_faces,
        dtype=torch.int32,
        device=device,
    )
    geometry_face_tensor = torch.tensor(
        geometry_faces,
        dtype=torch.int32,
        device=device,
    )

    try:
        context = dr.RasterizeCudaContext(device=device)
        raster, _ = dr.rasterize(
            context,
            uv_clip4[None],
            texture_face_tensor,
            (resolution, resolution),
            grad_db=False,
        )
        interpolated, _ = dr.interpolate(
            donor,
            raster,
            geometry_face_tensor,
        )
    except Exception as exc:
        raise PhotorealP3TeacherPointBakeError(
            f"canonical SMPL-X teacher-point rasterization failed: {exc}"
        ) from exc

    occupied = raster[0, :, :, 3] > 0
    occupied_count = int(occupied.sum().item())
    if occupied_count < 1024:
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point canonical UV coverage is implausibly small"
        )
    query = interpolated[0][occupied]
    teacher_xyz_tensor = torch.tensor(
        xyz_np,
        dtype=torch.float32,
        device=device,
    )
    teacher_rgb_tensor = torch.tensor(
        rgb_np,
        dtype=torch.float32,
        device=device,
    )
    sampled_rgb, distances = _nearest_teacher_rgb(
        torch=torch,
        query_points=query,
        teacher_xyz=teacher_xyz_tensor,
        teacher_rgb=teacher_rgb_tensor,
    )

    rgb_values = sampled_rgb.numpy()
    distance_values = distances.numpy()
    if rgb_values.shape != (occupied_count, 3):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point color transfer output shape is invalid"
        )
    if not bool(np.all(np.isfinite(distance_values))):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point transfer distances are non-finite"
        )

    canvas = np.zeros((resolution, resolution, 3), dtype=np.uint8)
    occupied_np = occupied.detach().cpu().numpy().astype(bool, copy=False)
    canvas[occupied_np] = np.rint(
        np.clip(rgb_values, 0.0, 1.0) * 255.0
    ).astype(np.uint8)
    padded, padded_mask = dilate_texture_gutter(
        np,
        canvas,
        occupied_np,
        gutter_pixels,
    )

    encoded = io.BytesIO()
    try:
        Image.fromarray(padded, mode="RGB").save(
            encoded,
            format="PNG",
            optimize=False,
        )
    except (OSError, ValueError) as exc:
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point baked basecolor PNG encoding failed"
        ) from exc
    png = encoded.getvalue()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point baked basecolor is not PNG"
        )

    padded_count = int(padded_mask.sum())
    p95 = float(np.quantile(distance_values, 0.95))
    maximum = float(np.max(distance_values))
    mean = float(np.mean(distance_values))
    metrics: dict[str, float | str] = {
        "appearance_method": "exavatar-gaussian-nearest-canonical-uv-v1",
        "canonical_uv_template_sha256": _sha256_path(template),
        "teacher_point_count": float(xyz_np.shape[0]),
        "baked_basecolor_sha256": _sha256_bytes(png),
        "bake_width": float(resolution),
        "bake_height": float(resolution),
        "bake_occupied_texel_count": float(occupied_count),
        "bake_occupied_ratio": float(
            occupied_count / (resolution * resolution)
        ),
        "bake_padded_texel_ratio": float(
            padded_count / (resolution * resolution)
        ),
        "bake_gutter_pixels": float(gutter_pixels),
        "teacher_point_distance_mean": mean,
        "teacher_point_distance_p95": p95,
        "teacher_point_distance_max": maximum,
    }
    if not all(
        isinstance(value, str)
        or (math.isfinite(float(value)) and float(value) >= 0.0)
        for value in metrics.values()
    ):
        raise PhotorealP3TeacherPointBakeError(
            "teacher-point bake metrics are invalid"
        )

    return list(texcoords), bound_faces, png, metrics
