from __future__ import annotations

import hashlib
import io
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


class CanonicalTextureBakeError(ValueError):
    pass


BAKE_RESOLUTION = 2048
BAKE_GUTTER_PIXELS = 8
BAKE_CHUNK_SIZE = 32768


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_bake_resolution(source_width: int, source_height: int) -> int:
    if isinstance(source_width, bool) or isinstance(source_height, bool):
        raise CanonicalTextureBakeError("source texture dimensions are invalid")
    if not isinstance(source_width, int) or not isinstance(source_height, int):
        raise CanonicalTextureBakeError("source texture dimensions are invalid")
    if source_width < 1 or source_height < 1:
        raise CanonicalTextureBakeError("source texture dimensions are invalid")
    return BAKE_RESOLUTION


def load_canonical_smplx_uv_template(
    path: str | Path,
) -> tuple[int, list[tuple[float, float]], list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    template = Path(path).expanduser().resolve()
    if not template.is_file():
        raise CanonicalTextureBakeError("canonical SMPL-X UV template is missing")
    try:
        lines = template.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CanonicalTextureBakeError("canonical SMPL-X UV template is invalid UTF-8") from exc

    vertex_count = 0
    texcoords: list[tuple[float, float]] = []
    geometry_faces: list[tuple[int, int, int]] = []
    texture_faces: list[tuple[int, int, int]] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("v "):
            fields = line.split()
            if len(fields) < 4:
                raise CanonicalTextureBakeError("canonical SMPL-X vertex row is invalid")
            try:
                values = tuple(float(value) for value in fields[1:4])
            except ValueError as exc:
                raise CanonicalTextureBakeError("canonical SMPL-X vertex row is invalid") from exc
            if not all(math.isfinite(value) for value in values):
                raise CanonicalTextureBakeError("canonical SMPL-X vertex row is non-finite")
            vertex_count += 1
            continue
        if line.startswith("vt "):
            fields = line.split()
            if len(fields) < 3:
                raise CanonicalTextureBakeError("canonical SMPL-X UV row is invalid")
            try:
                uv = (float(fields[1]), float(fields[2]))
            except ValueError as exc:
                raise CanonicalTextureBakeError("canonical SMPL-X UV row is invalid") from exc
            if not all(math.isfinite(value) for value in uv):
                raise CanonicalTextureBakeError("canonical SMPL-X UV row is non-finite")
            texcoords.append(uv)
            continue
        if line.startswith("f "):
            tokens = line.split()[1:]
            if len(tokens) != 3:
                raise CanonicalTextureBakeError("canonical SMPL-X UV topology must be triangular")
            vertices: list[int] = []
            uvs: list[int] = []
            for token in tokens:
                fields = token.split("/")
                if len(fields) < 2 or not fields[0] or not fields[1]:
                    raise CanonicalTextureBakeError("canonical SMPL-X face lacks UV indices")
                try:
                    vertex = int(fields[0]) - 1
                    uv = int(fields[1]) - 1
                except ValueError as exc:
                    raise CanonicalTextureBakeError("canonical SMPL-X face index is invalid") from exc
                vertices.append(vertex)
                uvs.append(uv)
            geometry_faces.append((vertices[0], vertices[1], vertices[2]))
            texture_faces.append((uvs[0], uvs[1], uvs[2]))

    if vertex_count < 3 or len(texcoords) < 3 or not geometry_faces:
        raise CanonicalTextureBakeError("canonical SMPL-X UV template is incomplete")
    for face in geometry_faces:
        if len(set(face)) != 3 or any(index < 0 or index >= vertex_count for index in face):
            raise CanonicalTextureBakeError("canonical SMPL-X geometry face is invalid")
    for face in texture_faces:
        if any(index < 0 or index >= len(texcoords) for index in face):
            raise CanonicalTextureBakeError("canonical SMPL-X UV face is invalid")
    return vertex_count, texcoords, geometry_faces, texture_faces


def bind_canonical_smplx_uvs(
    *,
    donor_vertex_count: int,
    donor_faces: Iterable[Sequence[int]],
    canonical_vertex_count: int,
    canonical_texcoords: Sequence[Sequence[float]],
    canonical_geometry_faces: Sequence[Sequence[int]],
    canonical_texture_faces: Sequence[Sequence[int]],
) -> list[list[tuple[int, int]]]:
    if donor_vertex_count != canonical_vertex_count:
        raise CanonicalTextureBakeError("canonical SMPL-X vertex count does not match fitted donor")
    donor = [tuple(int(value) for value in face) for face in donor_faces]
    geometry = [tuple(int(value) for value in face) for face in canonical_geometry_faces]
    texture = [tuple(int(value) for value in face) for face in canonical_texture_faces]
    if len(donor) != len(geometry) or len(geometry) != len(texture):
        raise CanonicalTextureBakeError("canonical SMPL-X face count does not match fitted donor")
    if donor != geometry:
        raise CanonicalTextureBakeError("canonical SMPL-X face order does not match fitted donor")
    texcoord_count = len(canonical_texcoords)
    result: list[list[tuple[int, int]]] = []
    for geometry_face, texture_face in zip(geometry, texture):
        if len(geometry_face) != 3 or len(texture_face) != 3:
            raise CanonicalTextureBakeError("canonical SMPL-X topology must be triangular")
        if any(uv < 0 or uv >= texcoord_count for uv in texture_face):
            raise CanonicalTextureBakeError("canonical SMPL-X UV face index is outside range")
        result.append([(geometry_face[i], texture_face[i]) for i in range(3)])
    return result


def dilate_texture_gutter(np: Any, rgb: Any, occupied: Any, pixels: int) -> tuple[Any, Any]:
    if isinstance(pixels, bool) or not isinstance(pixels, int) or pixels < 0 or pixels > 64:
        raise CanonicalTextureBakeError("texture gutter size is invalid")
    image = np.asarray(rgb).copy()
    mask = np.asarray(occupied, dtype=bool).copy()
    if image.ndim != 3 or image.shape[2] != 3 or mask.shape != image.shape[:2]:
        raise CanonicalTextureBakeError("texture gutter input shape is invalid")
    height, width = mask.shape
    for _ in range(pixels):
        pending = ~mask
        if not bool(np.any(pending)):
            break
        additions = np.zeros_like(mask)
        next_image = image.copy()
        # Fixed order makes overlapping growth deterministic.
        for dy, dx in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            src_y0 = max(0, -dy)
            src_y1 = min(height, height - dy)
            src_x0 = max(0, -dx)
            src_x1 = min(width, width - dx)
            dst_y0 = src_y0 + dy
            dst_y1 = src_y1 + dy
            dst_x0 = src_x0 + dx
            dst_x1 = src_x1 + dx
            source_mask = mask[src_y0:src_y1, src_x0:src_x1]
            destination_pending = pending[dst_y0:dst_y1, dst_x0:dst_x1]
            destination_free = ~additions[dst_y0:dst_y1, dst_x0:dst_x1]
            take = source_mask & destination_pending & destination_free
            if not bool(np.any(take)):
                continue
            destination = next_image[dst_y0:dst_y1, dst_x0:dst_x1]
            source = image[src_y0:src_y1, src_x0:src_x1]
            destination[take] = source[take]
            additions[dst_y0:dst_y1, dst_x0:dst_x1] |= take
        if not bool(np.any(additions)):
            break
        image = next_image
        mask |= additions
    return image, mask


def bake_sith_surface_to_canonical_smplx(
    *,
    torch: Any,
    np: Any,
    donor_positions: Any,
    donor_faces: Iterable[Sequence[int]],
    sith_repo: str | Path,
    source_mesh_obj: str | Path,
    source_texture_path: str | Path,
    device: Any,
) -> tuple[list[tuple[float, float]], list[list[tuple[int, int]]], bytes, dict[str, float | str]]:
    try:
        import nvdiffrast.torch as dr
        from PIL import Image
    except ImportError as exc:
        raise CanonicalTextureBakeError(f"canonical texture bake dependencies are unavailable: {exc}") from exc

    repo = Path(sith_repo).expanduser().resolve()
    source_mesh = Path(source_mesh_obj).expanduser().resolve()
    source_texture = Path(source_texture_path).expanduser().resolve()
    template = repo / "data" / "smplx_uv.obj"
    if not repo.is_dir() or not source_mesh.is_file() or not source_texture.is_file():
        raise CanonicalTextureBakeError("canonical texture bake authority paths are missing")

    vertex_count, texcoords, geometry_faces, texture_faces = load_canonical_smplx_uv_template(template)
    donor_tensor = donor_positions
    if not hasattr(donor_tensor, "shape"):
        donor_tensor = torch.tensor(donor_positions, dtype=torch.float32, device=device)
    else:
        donor_tensor = donor_tensor.to(device=device, dtype=torch.float32)
    if donor_tensor.ndim != 2 or tuple(donor_tensor.shape[1:]) != (3,):
        raise CanonicalTextureBakeError("fitted donor positions have invalid shape")
    bound_faces = bind_canonical_smplx_uvs(
        donor_vertex_count=int(donor_tensor.shape[0]),
        donor_faces=donor_faces,
        canonical_vertex_count=vertex_count,
        canonical_texcoords=texcoords,
        canonical_geometry_faces=geometry_faces,
        canonical_texture_faces=texture_faces,
    )

    try:
        with Image.open(source_texture) as source_image:
            source_width, source_height = source_image.size
    except (OSError, ValueError) as exc:
        raise CanonicalTextureBakeError("SiTH source texture cannot be decoded") from exc
    resolution = choose_bake_resolution(int(source_width), int(source_height))

    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    try:
        from recon.models.ops.mesh.closest_tex import closest_tex
        from recon.models.ops.mesh.load_obj import load_obj
    except ImportError as exc:
        raise CanonicalTextureBakeError(f"SiTH surface texture sampler is unavailable: {exc}") from exc

    try:
        source_v, source_f, source_tv, source_tf, materials = load_obj(str(source_mesh), load_materials=True)
    except Exception as exc:
        raise CanonicalTextureBakeError(f"SiTH source mesh/material load failed: {exc}") from exc
    if source_v.ndim != 2 or source_v.shape[1] != 3 or source_f.ndim != 2 or source_f.shape[1] != 3:
        raise CanonicalTextureBakeError("SiTH source mesh topology is invalid")
    if source_tv.ndim != 2 or source_tv.shape[1] != 2 or source_tf.ndim != 2 or source_tf.shape[1] != 4:
        raise CanonicalTextureBakeError("SiTH source texture topology is invalid")
    if not materials:
        raise CanonicalTextureBakeError("SiTH source mesh exposes no material")

    source_v = source_v.to(device=device, dtype=torch.float32).contiguous()
    source_f = source_f.to(device=device, dtype=torch.long).contiguous()
    source_tv = source_tv.to(device=device, dtype=torch.float32).contiguous()
    source_tf = source_tf.to(device=device, dtype=torch.long).contiguous()
    for material in materials.values():
        if not isinstance(material, dict):
            raise CanonicalTextureBakeError("SiTH source material is invalid")
        for key, value in list(material.items()):
            if hasattr(value, "to"):
                material[key] = value.to(device)

    uv = torch.tensor(texcoords, dtype=torch.float32, device=device)
    uv_clip = uv * torch.tensor([2.0, -2.0], dtype=torch.float32, device=device) + torch.tensor(
        [-1.0, 1.0], dtype=torch.float32, device=device
    )
    uv_clip4 = torch.cat(
        [uv_clip, torch.zeros_like(uv_clip[:, :1]), torch.ones_like(uv_clip[:, :1])], dim=1
    )
    texture_face_tensor = torch.tensor(texture_faces, dtype=torch.int32, device=device)
    geometry_face_tensor = torch.tensor(geometry_faces, dtype=torch.int32, device=device)

    try:
        context = dr.RasterizeCudaContext(device=device)
        rast, _ = dr.rasterize(
            context,
            uv_clip4[None, ...],
            texture_face_tensor,
            (resolution, resolution),
            grad_db=False,
        )
        interpolated, _ = dr.interpolate(donor_tensor, rast, geometry_face_tensor)
    except Exception as exc:
        raise CanonicalTextureBakeError(f"canonical SMPL-X UV rasterization failed: {exc}") from exc

    occupied = rast[0, :, :, 3] > 0
    occupied_count = int(occupied.sum().item())
    if occupied_count < 1024:
        raise CanonicalTextureBakeError("canonical SMPL-X UV rasterization coverage is implausibly small")
    points = interpolated[0][occupied]
    if points.ndim != 2 or points.shape[1] != 3:
        raise CanonicalTextureBakeError("canonical SMPL-X raster positions are invalid")

    sampled: list[Any] = []
    distances: list[Any] = []
    try:
        with torch.no_grad():
            for start in range(0, int(points.shape[0]), BAKE_CHUNK_SIZE):
                chunk = points[start:start + BAKE_CHUNK_SIZE]
                rgb, _normal, distance = closest_tex(
                    source_v,
                    source_f,
                    source_tv,
                    source_tf,
                    materials,
                    chunk,
                )
                sampled.append(rgb.detach().cpu())
                distances.append(distance.detach().abs().cpu().reshape(-1))
    except Exception as exc:
        raise CanonicalTextureBakeError(f"SiTH closest-surface texture bake failed: {exc}") from exc

    rgb_values = torch.cat(sampled, dim=0).numpy()
    distance_values = torch.cat(distances, dim=0).numpy()
    if rgb_values.shape != (occupied_count, 3) or distance_values.shape != (occupied_count,):
        raise CanonicalTextureBakeError("canonical texture bake output shape is invalid")
    if not bool(np.all(np.isfinite(rgb_values))) or not bool(np.all(np.isfinite(distance_values))):
        raise CanonicalTextureBakeError("canonical texture bake output is non-finite")
    if float(np.min(rgb_values)) < -1e-5 or float(np.max(rgb_values)) > 1.00001:
        raise CanonicalTextureBakeError("canonical texture bake RGB is outside source-derived range")

    canvas = np.zeros((resolution, resolution, 3), dtype=np.uint8)
    occupied_np = occupied.detach().cpu().numpy().astype(bool, copy=False)
    canvas[occupied_np] = np.rint(np.clip(rgb_values, 0.0, 1.0) * 255.0).astype(np.uint8)
    padded, padded_mask = dilate_texture_gutter(np, canvas, occupied_np, BAKE_GUTTER_PIXELS)

    output = io.BytesIO()
    try:
        Image.fromarray(padded, mode="RGB").save(output, format="PNG", optimize=False)
    except (OSError, ValueError) as exc:
        raise CanonicalTextureBakeError("canonical baked texture PNG encoding failed") from exc
    baked_png = output.getvalue()
    if not baked_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CanonicalTextureBakeError("canonical baked texture is not PNG")

    padded_count = int(padded_mask.sum())
    p95 = float(np.quantile(distance_values, 0.95))
    maximum = float(np.max(distance_values))
    metrics: dict[str, float | str] = {
        "appearance_method": "canonical-surface-bake-v1",
        "canonical_uv_template_sha256": _sha256_path(template),
        "source_texture_sha256": _sha256_path(source_texture),
        "baked_basecolor_sha256": _sha256_bytes(baked_png),
        "bake_width": float(resolution),
        "bake_height": float(resolution),
        "bake_occupied_texel_count": float(occupied_count),
        "bake_occupied_ratio": float(occupied_count / (resolution * resolution)),
        "bake_padded_texel_ratio": float(padded_count / (resolution * resolution)),
        "bake_gutter_pixels": float(BAKE_GUTTER_PIXELS),
        "bake_surface_distance_p95": p95,
        "bake_surface_distance_max": maximum,
        # Compatibility fields consumed by the unchanged donor fitter before
        # the baked metadata wrapper replaces appearance authority.
        "projection_distance_p95": p95,
        "projection_distance_max": maximum,
        "seam_seed_corner_ratio": 0.0,
        "projected_corner_count": float(len(bound_faces) * 3),
        "degenerate_source_candidate_count": 0.0,
        "maximum_local_source_face_candidates": 1.0,
    }
    if not all(
        isinstance(value, str) or (math.isfinite(float(value)) and float(value) >= 0.0)
        for value in metrics.values()
    ):
        raise CanonicalTextureBakeError("canonical texture bake metrics are invalid")
    return list(texcoords), bound_faces, baked_png, metrics
