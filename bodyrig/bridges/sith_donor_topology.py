from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence


class DonorTopologyError(ValueError):
    pass


def canonical_source_uv_map(
    *,
    source_vertex_count: int,
    texcoord_count: int,
    faces: Sequence[Sequence[tuple[int, int]]],
) -> tuple[dict[int, int], dict[str, float]]:
    """Choose one deterministic source UV for each textured source vertex.

    SiTH OBJ vertices may occur on multiple UV islands. For donor-topology v1 we
    intentionally choose the most frequently referenced UV per source vertex;
    ties resolve to the lowest UV index. This keeps mapping deterministic while
    preserving the exact source texture bytes. A later atlas/barycentric pass may
    improve seam fidelity without changing geometry authority.
    """

    if source_vertex_count < 3 or texcoord_count < 3:
        raise DonorTopologyError("source topology counts are invalid")
    counts: dict[int, Counter[int]] = {}
    face_count = 0
    for face in faces:
        if len(face) != 3:
            raise DonorTopologyError("source topology must be triangular")
        face_count += 1
        for raw_vertex, raw_uv in face:
            vertex = int(raw_vertex)
            uv = int(raw_uv)
            if not 0 <= vertex < source_vertex_count:
                raise DonorTopologyError("source face vertex index is outside range")
            if not 0 <= uv < texcoord_count:
                raise DonorTopologyError("source face UV index is outside range")
            counts.setdefault(vertex, Counter())[uv] += 1
    if face_count == 0 or not counts:
        raise DonorTopologyError("source topology contains no textured faces")

    mapping: dict[int, int] = {}
    multi_uv = 0
    for vertex, uv_counts in counts.items():
        if len(uv_counts) > 1:
            multi_uv += 1
        maximum = max(uv_counts.values())
        mapping[vertex] = min(uv for uv, count in uv_counts.items() if count == maximum)

    metrics = {
        "textured_source_vertex_count": float(len(mapping)),
        "multi_uv_source_vertex_count": float(multi_uv),
        "multi_uv_source_vertex_ratio": float(multi_uv / max(1, len(mapping))),
    }
    return mapping, metrics


def build_donor_faces(
    *,
    donor_faces: Iterable[Sequence[int]],
    donor_vertex_count: int,
    donor_to_source_vertex: Sequence[int],
    source_uv_map: dict[int, int],
) -> list[list[tuple[int, int]]]:
    """Bind stable donor faces to source-derived UVs without changing geometry."""

    if donor_vertex_count < 3 or len(donor_to_source_vertex) != donor_vertex_count:
        raise DonorTopologyError("donor vertex mapping length mismatch")
    result: list[list[tuple[int, int]]] = []
    for raw_face in donor_faces:
        if len(raw_face) != 3:
            raise DonorTopologyError("donor topology must be triangular")
        face: list[tuple[int, int]] = []
        unique: set[int] = set()
        for raw_vertex in raw_face:
            vertex = int(raw_vertex)
            if not 0 <= vertex < donor_vertex_count:
                raise DonorTopologyError("donor face vertex index is outside range")
            unique.add(vertex)
            source_vertex = int(donor_to_source_vertex[vertex])
            uv = source_uv_map.get(source_vertex)
            if uv is None:
                raise DonorTopologyError("donor appearance mapping selected an untextured source vertex")
            face.append((vertex, uv))
        if len(unique) != 3:
            raise DonorTopologyError("donor topology contains a degenerate index face")
        result.append(face)
    if not result:
        raise DonorTopologyError("donor topology contains no faces")
    return result
