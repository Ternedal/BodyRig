from __future__ import annotations

import math
from typing import Iterable, Sequence


class SurfaceUvTransferError(ValueError):
    pass


DISTANCE_EPSILON = 1e-12


def _vec3(value: Sequence[float], *, label: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise SurfaceUvTransferError(f"{label} must contain three coordinates")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise SurfaceUvTransferError(f"{label} contains a non-finite coordinate")
    return result  # type: ignore[return-value]


def _uv2(value: Sequence[float], *, label: str) -> tuple[float, float]:
    if len(value) != 2:
        raise SurfaceUvTransferError(f"{label} must contain two coordinates")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise SurfaceUvTransferError(f"{label} contains a non-finite coordinate")
    return result  # type: ignore[return-value]


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a: tuple[float, float, float], scalar: float) -> tuple[float, float, float]:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length_sq(a: tuple[float, float, float]) -> float:
    return _dot(a, a)


def _unit_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    normal = _cross(_sub(b, a), _sub(c, a))
    length_sq = _length_sq(normal)
    if length_sq <= DISTANCE_EPSILON:
        return None
    inverse = 1.0 / math.sqrt(length_sq)
    return _mul(normal, inverse)


def _closest_barycentric(
    point: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    """Closest point on triangle using Ericson region tests; return barycentrics + distance²."""

    ab = _sub(b, a)
    ac = _sub(c, a)
    ap = _sub(point, a)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return (1.0, 0.0, 0.0), _length_sq(ap)

    bp = _sub(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return (0.0, 1.0, 0.0), _length_sq(bp)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        denominator = d1 - d3
        if abs(denominator) <= DISTANCE_EPSILON:
            raise SurfaceUvTransferError("source triangle edge is numerically degenerate")
        v = d1 / denominator
        closest = _add(a, _mul(ab, v))
        return (1.0 - v, v, 0.0), _length_sq(_sub(point, closest))

    cp = _sub(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return (0.0, 0.0, 1.0), _length_sq(cp)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        denominator = d2 - d6
        if abs(denominator) <= DISTANCE_EPSILON:
            raise SurfaceUvTransferError("source triangle edge is numerically degenerate")
        w = d2 / denominator
        closest = _add(a, _mul(ac, w))
        return (1.0 - w, 0.0, w), _length_sq(_sub(point, closest))

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        bc = _sub(c, b)
        denominator = (d4 - d3) + (d5 - d6)
        if abs(denominator) <= DISTANCE_EPSILON:
            raise SurfaceUvTransferError("source triangle edge is numerically degenerate")
        w = (d4 - d3) / denominator
        closest = _add(b, _mul(bc, w))
        return (0.0, 1.0 - w, w), _length_sq(_sub(point, closest))

    denominator = va + vb + vc
    if abs(denominator) <= DISTANCE_EPSILON:
        raise SurfaceUvTransferError("source triangle is numerically degenerate")
    inverse = 1.0 / denominator
    v = vb * inverse
    w = vc * inverse
    u = 1.0 - v - w
    closest = _add(_add(_mul(a, u), _mul(b, v)), _mul(c, w))
    return (u, v, w), _length_sq(_sub(point, closest))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def build_surface_projected_donor_uvs(
    *,
    donor_faces: Iterable[Sequence[int]],
    donor_positions: Sequence[Sequence[float]],
    source_positions: Sequence[Sequence[float]],
    source_faces: Sequence[Sequence[tuple[int, int]]],
    source_texcoords: Sequence[Sequence[float]],
    donor_to_source_vertex: Sequence[int],
) -> tuple[list[tuple[float, float]], list[list[tuple[int, int]]], dict[str, float]]:
    """Project each donor face corner onto a nearby textured source triangle.

    Nearest-source vertices are used only as a local search seed. The final UV is
    barycentrically interpolated from the closest incident source triangle. Each
    donor face corner receives its own UV index, so source atlas seams can remain
    face-local instead of being collapsed to one canonical UV per source vertex.
    Geometry indices are never changed.
    """

    donor = [_vec3(row, label="donor position") for row in donor_positions]
    source = [_vec3(row, label="source position") for row in source_positions]
    texcoords = [_uv2(row, label="source UV") for row in source_texcoords]
    if len(donor) < 3 or len(source) < 3 or len(texcoords) < 3:
        raise SurfaceUvTransferError("surface UV topology counts are invalid")
    if len(donor_to_source_vertex) != len(donor):
        raise SurfaceUvTransferError("donor nearest-source mapping length mismatch")

    parsed_source_faces: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = []
    adjacency: dict[int, list[int]] = {}
    source_normals: list[tuple[float, float, float] | None] = []
    for face_index, raw_face in enumerate(source_faces):
        if len(raw_face) != 3:
            raise SurfaceUvTransferError("source UV topology must be triangular")
        parsed: list[tuple[int, int]] = []
        unique_vertices: set[int] = set()
        for raw_vertex, raw_uv in raw_face:
            vertex = int(raw_vertex)
            uv = int(raw_uv)
            if not 0 <= vertex < len(source) or not 0 <= uv < len(texcoords):
                raise SurfaceUvTransferError("source UV face index is outside range")
            parsed.append((vertex, uv))
            unique_vertices.add(vertex)
        if len(unique_vertices) != 3:
            raise SurfaceUvTransferError("source UV topology contains a degenerate index face")
        face_tuple = (parsed[0], parsed[1], parsed[2])
        parsed_source_faces.append(face_tuple)
        normal = _unit_normal(source[parsed[0][0]], source[parsed[1][0]], source[parsed[2][0]])
        source_normals.append(normal)
        for vertex in unique_vertices:
            adjacency.setdefault(vertex, []).append(face_index)
    if not parsed_source_faces:
        raise SurfaceUvTransferError("source UV topology contains no faces")

    projected_uvs: list[tuple[float, float]] = []
    projected_faces: list[list[tuple[int, int]]] = []
    projection_distances: list[float] = []
    seam_seed_corners = 0
    degenerate_candidates = 0
    maximum_candidates = 0

    for raw_face in donor_faces:
        if len(raw_face) != 3:
            raise SurfaceUvTransferError("donor UV topology must be triangular")
        donor_vertices = [int(value) for value in raw_face]
        if len(set(donor_vertices)) != 3 or any(vertex < 0 or vertex >= len(donor) for vertex in donor_vertices):
            raise SurfaceUvTransferError("donor UV face indices are invalid")
        donor_normal = _unit_normal(
            donor[donor_vertices[0]], donor[donor_vertices[1]], donor[donor_vertices[2]]
        )
        if donor_normal is None:
            raise SurfaceUvTransferError("donor UV topology contains a geometric degenerate face")

        output_face: list[tuple[int, int]] = []
        for donor_vertex in donor_vertices:
            source_seed = int(donor_to_source_vertex[donor_vertex])
            candidates = adjacency.get(source_seed)
            if source_seed < 0 or source_seed >= len(source) or not candidates:
                raise SurfaceUvTransferError("donor UV mapping selected an untextured source vertex")
            maximum_candidates = max(maximum_candidates, len(candidates))
            seed_uvs = {
                uv
                for face_index in candidates
                for vertex, uv in parsed_source_faces[face_index]
                if vertex == source_seed
            }
            if len(seed_uvs) > 1:
                seam_seed_corners += 1

            point = donor[donor_vertex]
            best: tuple[float, float, int, tuple[float, float, float], float] | None = None
            for face_index in candidates:
                source_face = parsed_source_faces[face_index]
                normal = source_normals[face_index]
                if normal is None:
                    degenerate_candidates += 1
                    continue
                a = source[source_face[0][0]]
                b = source[source_face[1][0]]
                c = source[source_face[2][0]]
                try:
                    barycentric, distance_sq = _closest_barycentric(point, a, b, c)
                except SurfaceUvTransferError:
                    degenerate_candidates += 1
                    continue
                normal_alignment = max(-1.0, min(1.0, _dot(donor_normal, normal)))
                distance_key = round(distance_sq, 12)
                candidate = (distance_key, -normal_alignment, face_index, barycentric, distance_sq)
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
            if best is None:
                raise SurfaceUvTransferError("donor UV corner has no non-degenerate local source triangle")

            _, _negative_alignment, face_index, barycentric, distance_sq = best
            source_face = parsed_source_faces[face_index]
            uv0 = texcoords[source_face[0][1]]
            uv1 = texcoords[source_face[1][1]]
            uv2 = texcoords[source_face[2][1]]
            u = barycentric[0] * uv0[0] + barycentric[1] * uv1[0] + barycentric[2] * uv2[0]
            v = barycentric[0] * uv0[1] + barycentric[1] * uv1[1] + barycentric[2] * uv2[1]
            if not math.isfinite(u) or not math.isfinite(v) or distance_sq < -DISTANCE_EPSILON:
                raise SurfaceUvTransferError("projected donor UV is non-finite")
            uv_index = len(projected_uvs)
            projected_uvs.append((u, v))
            output_face.append((donor_vertex, uv_index))
            projection_distances.append(math.sqrt(max(0.0, distance_sq)))
        projected_faces.append(output_face)

    if not projected_faces or len(projected_uvs) != len(projected_faces) * 3:
        raise SurfaceUvTransferError("projected donor UV output is incomplete")

    metrics = {
        "projected_corner_count": float(len(projected_uvs)),
        "projection_distance_p95": _percentile(projection_distances, 0.95),
        "projection_distance_max": max(projection_distances),
        "seam_seed_corner_ratio": float(seam_seed_corners / max(1, len(projected_uvs))),
        "degenerate_source_candidate_count": float(degenerate_candidates),
        "maximum_local_source_face_candidates": float(maximum_candidates),
    }
    if not all(math.isfinite(value) and value >= 0.0 for value in metrics.values()):
        raise SurfaceUvTransferError("projected donor UV metrics are invalid")
    return projected_uvs, projected_faces, metrics
