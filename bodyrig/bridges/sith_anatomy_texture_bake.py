from __future__ import annotations

import io
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import sith_canonical_texture_bake as canonical


class AnatomyTextureBakeError(ValueError):
    pass


REGION_NAMES = (
    "torso",
    "head",
    "left_arm",
    "right_arm",
    "left_leg",
    "right_leg",
)
REGION_INDEX = {name: index for index, name in enumerate(REGION_NAMES)}
NORMAL_RETRY_COSINE = 0.50
NORMAL_PENALTY_SCALE = 0.020
NORMAL_RETRY_OFFSETS = (0.003, 0.008)
SOURCE_VERTEX_CHUNK = 1024
DONOR_VERTEX_TILE = 4096
MIN_REGION_FACE_COUNT = 32


def appearance_joint_region(name: str) -> str:
    lowered = name.strip().lower().replace("-", "_")
    if lowered.startswith("smplx_"):
        lowered = lowered[len("smplx_") :]
    if lowered in {"neck", "head", "jaw", "left_eye", "right_eye"}:
        return "head"
    if lowered.startswith("left_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "left_leg"
        return "left_arm"
    if lowered.startswith("right_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "right_leg"
        return "right_arm"
    return "torso"


def joint_region_indices(joint_names: Sequence[str]) -> list[int]:
    if not joint_names:
        raise AnatomyTextureBakeError("SMPL-X joint names are missing")
    return [REGION_INDEX[appearance_joint_region(name)] for name in joint_names]


def normal_candidate_score(*, distance: float, alignment: float, body_scale: float, offset: float) -> float:
    values = (distance, alignment, body_scale, offset)
    if not all(math.isfinite(float(value)) for value in values):
        raise AnatomyTextureBakeError("normal-aware candidate score input is non-finite")
    if distance < 0.0 or body_scale <= 0.0 or offset < 0.0:
        raise AnatomyTextureBakeError("normal-aware candidate score input is outside range")
    cosine = max(-1.0, min(1.0, float(alignment)))
    return float(distance) + float(offset) + float(body_scale) * NORMAL_PENALTY_SCALE * (1.0 - cosine)


def source_face_region_memberships(source_vertex_regions: Sequence[int], faces: Iterable[Sequence[int]]) -> list[set[int]]:
    memberships: list[set[int]] = []
    region_count = len(REGION_NAMES)
    for face in faces:
        values = tuple(int(value) for value in face)
        if len(values) != 3:
            raise AnatomyTextureBakeError("source face is not triangular")
        if any(index < 0 or index >= len(source_vertex_regions) for index in values):
            raise AnatomyTextureBakeError("source face vertex index is outside range")
        regions = {int(source_vertex_regions[index]) for index in values}
        if not regions or any(region < 0 or region >= region_count for region in regions):
            raise AnatomyTextureBakeError("source face region is invalid")
        memberships.append(regions)
    return memberships


def _load_donor_region_scores(
    *,
    torch: Any,
    model_dir: str | Path,
    gender: str,
    device: Any,
    donor_vertex_count: int,
) -> Any:
    try:
        from smplx import SMPLX
        from sith_smplx_vrm_fitter import SMPLX_JOINT_NAMES
    except ImportError as exc:
        raise AnatomyTextureBakeError(f"SMPL-X anatomy authority is unavailable: {exc}") from exc
    try:
        model = SMPLX(
            model_path=str(Path(model_dir).expanduser().resolve()),
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise AnatomyTextureBakeError("failed to load SMPL-X anatomy authority") from exc
    weights = model.lbs_weights.to(device=device, dtype=torch.float32)
    if weights.ndim != 2 or int(weights.shape[0]) != donor_vertex_count:
        raise AnatomyTextureBakeError("SMPL-X anatomy weights do not match donor topology")
    if int(weights.shape[1]) != len(SMPLX_JOINT_NAMES):
        raise AnatomyTextureBakeError("SMPL-X anatomy joint count is incompatible")
    region_ids = joint_region_indices(SMPLX_JOINT_NAMES)
    joint_to_region = torch.zeros(
        (len(region_ids), len(REGION_NAMES)),
        dtype=torch.float32,
        device=device,
    )
    for joint, region in enumerate(region_ids):
        joint_to_region[joint, region] = 1.0
    scores = weights @ joint_to_region
    totals = scores.sum(dim=1)
    if bool(torch.any(torch.abs(totals - 1.0) > 1e-4).item()):
        raise AnatomyTextureBakeError("SMPL-X anatomy region weights do not sum to one")
    return scores


def _nearest_donor_regions(
    *,
    torch: Any,
    source_vertices: Any,
    donor_vertices: Any,
    donor_region_ids: Any,
    device: Any,
) -> Any:
    source_count = int(source_vertices.shape[0])
    donor_count = int(donor_vertices.shape[0])
    result = torch.empty((source_count,), dtype=torch.long, device=device)
    with torch.no_grad():
        for source_start in range(0, source_count, SOURCE_VERTEX_CHUNK):
            source = source_vertices[source_start:source_start + SOURCE_VERTEX_CHUNK]
            count = int(source.shape[0])
            best_distance = torch.full((count,), float("inf"), dtype=torch.float32, device=device)
            best_donor = torch.full((count,), -1, dtype=torch.long, device=device)
            for donor_start in range(0, donor_count, DONOR_VERTEX_TILE):
                donor = donor_vertices[donor_start:donor_start + DONOR_VERTEX_TILE]
                distance = torch.cdist(source.unsqueeze(0), donor.unsqueeze(0)).squeeze(0)
                tile_distance, tile_local = torch.min(distance, dim=1)
                improve = tile_distance < best_distance
                if bool(torch.any(improve).item()):
                    best_distance = torch.where(improve, tile_distance, best_distance)
                    best_donor = torch.where(improve, donor_start + tile_local, best_donor)
            if bool(torch.any(best_donor < 0).item()):
                raise AnatomyTextureBakeError("source anatomy mapping is incomplete")
            result[source_start:source_start + count] = donor_region_ids[best_donor]
    return result


def _face_normals(torch: Any, vertices: Any, faces: Any) -> tuple[Any, Any]:
    a = vertices[faces[:, 0].long()]
    b = vertices[faces[:, 1].long()]
    c = vertices[faces[:, 2].long()]
    normals = torch.cross(b - a, c - a, dim=1)
    lengths = torch.linalg.vector_norm(normals, dim=1, keepdim=True)
    valid = lengths[:, 0] > 1e-10
    safe = torch.where(valid[:, None], normals / torch.clamp(lengths, min=1e-10), torch.zeros_like(normals))
    return safe, valid


def _body_scale(torch: Any, vertices: Any) -> float:
    span = torch.max(vertices, dim=0).values - torch.min(vertices, dim=0).values
    value = float(torch.linalg.vector_norm(span).item())
    if not math.isfinite(value) or value <= 1e-6:
        raise AnatomyTextureBakeError("donor body scale is invalid")
    return value


def _sample_region(
    *,
    torch: Any,
    closest_tex: Any,
    points: Any,
    donor_normals: Any,
    donor_normals_valid: Any,
    source_v: Any,
    source_f: Any,
    source_tv: Any,
    source_tf: Any,
    materials: Any,
    body_scale: float,
) -> tuple[Any, Any, Any, int]:
    count = int(points.shape[0])
    rgb_out = torch.empty((count, 3), dtype=torch.float32, device=points.device)
    distance_out = torch.empty((count,), dtype=torch.float32, device=points.device)
    alignment_out = torch.ones((count,), dtype=torch.float32, device=points.device)
    retry_count = 0

    with torch.no_grad():
        for start in range(0, count, canonical.BAKE_CHUNK_SIZE):
            chunk = points[start:start + canonical.BAKE_CHUNK_SIZE]
            normals = donor_normals[start:start + canonical.BAKE_CHUNK_SIZE]
            normals_valid = donor_normals_valid[start:start + canonical.BAKE_CHUNK_SIZE]
            rgb, source_normal, raw_distance = closest_tex(
                source_v,
                source_f,
                source_tv,
                source_tf,
                materials,
                chunk,
            )
            distance = raw_distance.detach().abs().reshape(-1)
            source_normal = source_normal.to(dtype=torch.float32)
            source_length = torch.linalg.vector_norm(source_normal, dim=1, keepdim=True)
            source_valid = source_length[:, 0] > 1e-10
            source_unit = torch.where(
                source_valid[:, None],
                source_normal / torch.clamp(source_length, min=1e-10),
                torch.zeros_like(source_normal),
            )
            alignment = torch.sum(normals * source_unit, dim=1)
            comparison_valid = normals_valid & source_valid
            alignment = torch.where(comparison_valid, alignment, torch.ones_like(alignment))
            alignment = torch.clamp(alignment, -1.0, 1.0)

            best_rgb = rgb
            best_distance = distance
            best_alignment = alignment
            best_score = distance + body_scale * NORMAL_PENALTY_SCALE * (1.0 - alignment)
            retry = comparison_valid & (alignment < NORMAL_RETRY_COSINE)
            retry_count += int(retry.sum().item())

            if bool(torch.any(retry).item()):
                retry_indices = torch.nonzero(retry, as_tuple=False).reshape(-1)
                retry_points = chunk[retry_indices]
                retry_normals = normals[retry_indices]
                for ratio in NORMAL_RETRY_OFFSETS:
                    offset = float(body_scale * ratio)
                    query = retry_points + retry_normals * offset
                    candidate_rgb, candidate_normal, candidate_raw_distance = closest_tex(
                        source_v,
                        source_f,
                        source_tv,
                        source_tf,
                        materials,
                        query,
                    )
                    candidate_distance = candidate_raw_distance.detach().abs().reshape(-1)
                    candidate_length = torch.linalg.vector_norm(candidate_normal, dim=1, keepdim=True)
                    candidate_valid = candidate_length[:, 0] > 1e-10
                    candidate_unit = torch.where(
                        candidate_valid[:, None],
                        candidate_normal / torch.clamp(candidate_length, min=1e-10),
                        torch.zeros_like(candidate_normal),
                    )
                    candidate_alignment = torch.sum(retry_normals * candidate_unit, dim=1)
                    candidate_alignment = torch.where(
                        candidate_valid,
                        torch.clamp(candidate_alignment, -1.0, 1.0),
                        torch.full_like(candidate_alignment, -1.0),
                    )
                    candidate_score = (
                        candidate_distance
                        + offset
                        + body_scale * NORMAL_PENALTY_SCALE * (1.0 - candidate_alignment)
                    )
                    current_score = best_score[retry_indices]
                    improve = candidate_score < current_score
                    if bool(torch.any(improve).item()):
                        target = retry_indices[improve]
                        best_score[target] = candidate_score[improve]
                        best_rgb[target] = candidate_rgb[improve]
                        best_distance[target] = candidate_distance[improve] + offset
                        best_alignment[target] = candidate_alignment[improve]

            end = start + int(chunk.shape[0])
            rgb_out[start:end] = best_rgb
            distance_out[start:end] = best_distance
            alignment_out[start:end] = best_alignment

    return rgb_out, distance_out, alignment_out, retry_count


def bake_sith_surface_to_anatomy_canonical_smplx(
    *,
    torch: Any,
    np: Any,
    donor_positions: Any,
    donor_faces: Iterable[Sequence[int]],
    sith_repo: str | Path,
    source_mesh_obj: str | Path,
    source_texture_path: str | Path,
    model_dir: str | Path,
    gender: str,
    device: Any,
    resolution: int,
) -> tuple[list[tuple[float, float]], list[list[tuple[int, int]]], bytes, dict[str, float | str]]:
    try:
        import nvdiffrast.torch as dr
        from PIL import Image
    except ImportError as exc:
        raise AnatomyTextureBakeError(f"anatomy texture bake dependencies are unavailable: {exc}") from exc
    if gender not in {"female", "male", "neutral"}:
        raise AnatomyTextureBakeError("SMPL-X anatomy gender is invalid")
    if isinstance(resolution, bool) or not isinstance(resolution, int) or resolution < 256 or resolution > 4096:
        raise AnatomyTextureBakeError("anatomy bake resolution is invalid")

    repo = Path(sith_repo).expanduser().resolve()
    source_mesh = Path(source_mesh_obj).expanduser().resolve()
    source_texture = Path(source_texture_path).expanduser().resolve()
    template = repo / "data" / "smplx_uv.obj"
    if not repo.is_dir() or not source_mesh.is_file() or not source_texture.is_file():
        raise AnatomyTextureBakeError("anatomy texture bake authority paths are missing")

    vertex_count, texcoords, geometry_faces, texture_faces = canonical.load_canonical_smplx_uv_template(template)
    donor_tensor = donor_positions
    if not hasattr(donor_tensor, "shape"):
        donor_tensor = torch.tensor(donor_positions, dtype=torch.float32, device=device)
    else:
        donor_tensor = donor_tensor.to(device=device, dtype=torch.float32)
    if donor_tensor.ndim != 2 or tuple(donor_tensor.shape[1:]) != (3,):
        raise AnatomyTextureBakeError("fitted donor positions have invalid shape")
    bound_faces = canonical.bind_canonical_smplx_uvs(
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
        raise AnatomyTextureBakeError("SiTH source texture cannot be decoded") from exc
    if source_width < 1 or source_height < 1:
        raise AnatomyTextureBakeError("SiTH source texture dimensions are invalid")

    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    try:
        from recon.models.ops.mesh.closest_tex import closest_tex
        from recon.models.ops.mesh.load_obj import load_obj
    except ImportError as exc:
        raise AnatomyTextureBakeError(f"SiTH surface sampler is unavailable: {exc}") from exc
    try:
        source_v, source_f, source_tv, source_tf, materials = load_obj(str(source_mesh), load_materials=True)
    except Exception as exc:
        raise AnatomyTextureBakeError(f"SiTH source mesh/material load failed: {exc}") from exc
    if source_v.ndim != 2 or source_v.shape[1] != 3 or source_f.ndim != 2 or source_f.shape[1] != 3:
        raise AnatomyTextureBakeError("SiTH source mesh topology is invalid")
    if source_tv.ndim != 2 or source_tv.shape[1] != 2 or source_tf.ndim != 2 or source_tf.shape[1] != 4:
        raise AnatomyTextureBakeError("SiTH source texture topology is invalid")
    if int(source_tf.shape[0]) != int(source_f.shape[0]) or not materials:
        raise AnatomyTextureBakeError("SiTH source face/material topology is invalid")

    source_v = source_v.to(device=device, dtype=torch.float32).contiguous()
    source_f = source_f.to(device=device, dtype=torch.long).contiguous()
    source_tv = source_tv.to(device=device, dtype=torch.float32).contiguous()
    source_tf = source_tf.to(device=device, dtype=torch.long).contiguous()
    for material in materials.values():
        if not isinstance(material, dict):
            raise AnatomyTextureBakeError("SiTH source material is invalid")
        for key, value in list(material.items()):
            if hasattr(value, "to"):
                material[key] = value.to(device)

    donor_scores = _load_donor_region_scores(
        torch=torch,
        model_dir=model_dir,
        gender=gender,
        device=device,
        donor_vertex_count=int(donor_tensor.shape[0]),
    )
    donor_region_ids = torch.argmax(donor_scores, dim=1)
    geometry_face_tensor_long = torch.tensor(geometry_faces, dtype=torch.long, device=device)
    donor_face_scores = donor_scores[geometry_face_tensor_long].mean(dim=1)
    donor_face_regions = torch.argmax(donor_face_scores, dim=1)

    source_vertex_regions = _nearest_donor_regions(
        torch=torch,
        source_vertices=source_v,
        donor_vertices=donor_tensor,
        donor_region_ids=donor_region_ids,
        device=device,
    )
    source_face_vertex_regions = source_vertex_regions[source_f.long()]
    region_face_masks = [
        torch.any(source_face_vertex_regions == region, dim=1)
        for region in range(len(REGION_NAMES))
    ]
    for region, mask in enumerate(region_face_masks):
        if int(mask.sum().item()) < MIN_REGION_FACE_COUNT:
            raise AnatomyTextureBakeError(
                f"source anatomy region {REGION_NAMES[region]} exposes too few candidate faces"
            )

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
        raise AnatomyTextureBakeError(f"canonical SMPL-X UV rasterization failed: {exc}") from exc

    occupied = rast[0, :, :, 3] > 0
    occupied_count = int(occupied.sum().item())
    if occupied_count < 1024:
        raise AnatomyTextureBakeError("canonical SMPL-X UV rasterization coverage is implausibly small")
    points = interpolated[0][occupied]
    face_ids = rast[0, :, :, 3].long()[occupied] - 1
    if bool(torch.any(face_ids < 0).item()) or bool(torch.any(face_ids >= len(geometry_faces)).item()):
        raise AnatomyTextureBakeError("canonical raster face authority is invalid")
    point_regions = donor_face_regions[face_ids]
    face_normals, face_normals_valid = _face_normals(torch, donor_tensor, geometry_face_tensor_long)
    point_normals = face_normals[face_ids]
    point_normals_valid = face_normals_valid[face_ids]
    body_scale = _body_scale(torch, donor_tensor)

    rgb_values_gpu = torch.empty((occupied_count, 3), dtype=torch.float32, device=device)
    distance_values_gpu = torch.empty((occupied_count,), dtype=torch.float32, device=device)
    alignment_values_gpu = torch.ones((occupied_count,), dtype=torch.float32, device=device)
    retry_total = 0
    region_texel_counts: list[int] = []

    try:
        for region in range(len(REGION_NAMES)):
            point_mask = point_regions == region
            point_indices = torch.nonzero(point_mask, as_tuple=False).reshape(-1)
            region_texel_counts.append(int(point_indices.numel()))
            if int(point_indices.numel()) == 0:
                raise AnatomyTextureBakeError(f"canonical atlas exposes no texels for {REGION_NAMES[region]}")
            face_mask = region_face_masks[region]
            region_source_f = source_f[face_mask].contiguous()
            region_source_tf = source_tf[face_mask].contiguous()
            rgb, distance, alignment, retries = _sample_region(
                torch=torch,
                closest_tex=closest_tex,
                points=points[point_indices],
                donor_normals=point_normals[point_indices],
                donor_normals_valid=point_normals_valid[point_indices],
                source_v=source_v,
                source_f=region_source_f,
                source_tv=source_tv,
                source_tf=region_source_tf,
                materials=materials,
                body_scale=body_scale,
            )
            rgb_values_gpu[point_indices] = rgb
            distance_values_gpu[point_indices] = distance
            alignment_values_gpu[point_indices] = alignment
            retry_total += retries
    except AnatomyTextureBakeError:
        raise
    except Exception as exc:
        raise AnatomyTextureBakeError(f"anatomy-aware SiTH surface bake failed: {exc}") from exc

    rgb_values = rgb_values_gpu.detach().cpu().numpy()
    distance_values = distance_values_gpu.detach().cpu().numpy()
    alignment_values = alignment_values_gpu.detach().cpu().numpy()
    if rgb_values.shape != (occupied_count, 3) or distance_values.shape != (occupied_count,):
        raise AnatomyTextureBakeError("anatomy texture bake output shape is invalid")
    if not bool(np.all(np.isfinite(rgb_values))) or not bool(np.all(np.isfinite(distance_values))):
        raise AnatomyTextureBakeError("anatomy texture bake output is non-finite")
    if not bool(np.all(np.isfinite(alignment_values))):
        raise AnatomyTextureBakeError("anatomy normal alignment output is non-finite")
    if float(np.min(rgb_values)) < -1e-5 or float(np.max(rgb_values)) > 1.00001:
        raise AnatomyTextureBakeError("anatomy texture bake RGB is outside source-derived range")

    canvas = np.zeros((resolution, resolution, 3), dtype=np.uint8)
    occupied_np = occupied.detach().cpu().numpy().astype(bool, copy=False)
    canvas[occupied_np] = np.rint(np.clip(rgb_values, 0.0, 1.0) * 255.0).astype(np.uint8)
    padded, padded_mask = canonical.dilate_texture_gutter(
        np,
        canvas,
        occupied_np,
        canonical.BAKE_GUTTER_PIXELS,
    )
    output = io.BytesIO()
    try:
        Image.fromarray(padded, mode="RGB").save(output, format="PNG", optimize=False)
    except (OSError, ValueError) as exc:
        raise AnatomyTextureBakeError("anatomy baked texture PNG encoding failed") from exc
    baked_png = output.getvalue()
    if not baked_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AnatomyTextureBakeError("anatomy baked texture is not PNG")

    padded_count = int(padded_mask.sum())
    p95 = float(np.quantile(distance_values, 0.95))
    maximum = float(np.max(distance_values))
    alignment_mean = float(np.mean(alignment_values))
    alignment_p05 = float(np.quantile(alignment_values, 0.05))
    low_alignment_ratio = float(np.mean(alignment_values < NORMAL_RETRY_COSINE))
    metrics: dict[str, float | str] = {
        "appearance_method": "canonical-anatomy-normal-bake-v2",
        "canonical_uv_template_sha256": canonical._sha256_path(template),
        "source_texture_sha256": canonical._sha256_path(source_texture),
        "baked_basecolor_sha256": canonical._sha256_bytes(baked_png),
        "bake_width": float(resolution),
        "bake_height": float(resolution),
        "bake_occupied_texel_count": float(occupied_count),
        "bake_occupied_ratio": float(occupied_count / (resolution * resolution)),
        "bake_padded_texel_ratio": float(padded_count / (resolution * resolution)),
        "bake_gutter_pixels": float(canonical.BAKE_GUTTER_PIXELS),
        "bake_surface_distance_p95": p95,
        "bake_surface_distance_max": maximum,
        "anatomy_region_count": float(len(REGION_NAMES)),
        "anatomy_restricted_texel_ratio": 1.0,
        "normal_retry_texel_count": float(retry_total),
        "normal_retry_texel_ratio": float(retry_total / occupied_count),
        "normal_alignment_mean": alignment_mean,
        "normal_alignment_p05": alignment_p05,
        "normal_low_alignment_ratio": low_alignment_ratio,
        "body_scale": body_scale,
        "projection_distance_p95": p95,
        "projection_distance_max": maximum,
        "seam_seed_corner_ratio": 0.0,
        "projected_corner_count": float(len(bound_faces) * 3),
        "degenerate_source_candidate_count": 0.0,
        "maximum_local_source_face_candidates": 1.0,
    }
    for region, count in enumerate(region_texel_counts):
        metrics[f"region_{REGION_NAMES[region]}_texel_ratio"] = float(count / occupied_count)
    if not all(
        isinstance(value, str) or math.isfinite(float(value))
        for value in metrics.values()
    ):
        raise AnatomyTextureBakeError("anatomy texture bake metrics are invalid")
    return list(texcoords), bound_faces, baked_png, metrics
