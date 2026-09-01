from __future__ import annotations

import pytest

from bodyrig.bridges.sith_surface_uv_transfer import build_surface_projected_donor_uvs


def test_non_seam_shared_donor_vertex_reuses_one_uv_coordinate() -> None:
    # Two folded source triangles share the same UV at source vertex 0. A donor
    # vertex sits equally far from both source faces and participates in donor
    # faces whose normals prefer different source triangles. The shared donor
    # vertex must nevertheless keep one UV coordinate because its source seed is
    # not a UV seam.
    source_positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    source_texcoords = [
        (0.10, 0.10),
        (0.90, 0.10),
        (0.10, 0.90),
        (0.10, -0.70),
    ]
    source_faces = [
        [(0, 0), (1, 1), (2, 2)],
        [(0, 0), (3, 3), (1, 1)],
    ]
    donor_positions = [
        (0.0, 0.2, 0.2),
        (0.8, 0.2, 0.0),
        (0.0, 0.8, 0.0),
        (0.0, 0.0, 0.8),
        (0.8, 0.0, 0.2),
    ]

    texcoords, faces, metrics = build_surface_projected_donor_uvs(
        donor_faces=[(0, 1, 2), (0, 3, 4)],
        donor_positions=donor_positions,
        source_positions=source_positions,
        source_faces=source_faces,
        source_texcoords=source_texcoords,
        donor_to_source_vertex=[0, 1, 2, 3, 1],
    )

    first_shared_uv = texcoords[faces[0][0][1]]
    second_shared_uv = texcoords[faces[1][0][1]]

    assert first_shared_uv == pytest.approx(second_shared_uv, abs=1e-10)
    assert metrics["continuous_donor_vertex_count"] >= 1.0
    assert metrics["continuous_reused_corner_count"] >= 1.0
    assert metrics["seam_seed_corner_ratio"] == pytest.approx(0.0)
