from __future__ import annotations

import math

import pytest

from bodyrig.bridges.sith_surface_uv_transfer import (
    SurfaceUvTransferError,
    build_surface_projected_donor_uvs,
)


def test_surface_projection_preserves_triangle_uvs_for_exact_geometry() -> None:
    texcoords, faces, metrics = build_surface_projected_donor_uvs(
        donor_faces=[(0, 1, 2)],
        donor_positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        source_positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        source_faces=[[(0, 0), (1, 1), (2, 2)]],
        source_texcoords=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        donor_to_source_vertex=[0, 1, 2],
    )

    assert faces == [[(0, 0), (1, 1), (2, 2)]]
    assert texcoords == pytest.approx([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    assert metrics["projected_corner_count"] == 3.0
    assert metrics["projection_distance_p95"] == pytest.approx(0.0)
    assert metrics["projection_distance_max"] == pytest.approx(0.0)
    assert metrics["degenerate_donor_face_count"] == 0.0


def test_surface_projection_interpolates_uv_inside_source_triangle() -> None:
    texcoords, _faces, metrics = build_surface_projected_donor_uvs(
        donor_faces=[(0, 1, 2)],
        donor_positions=[(0.25, 0.25, 0.0), (0.50, 0.20, 0.0), (0.20, 0.50, 0.0)],
        source_positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        source_faces=[[(0, 0), (1, 1), (2, 2)]],
        source_texcoords=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        donor_to_source_vertex=[0, 1, 2],
    )

    assert texcoords[0] == pytest.approx((0.25, 0.25), abs=1e-8)
    assert texcoords[1] == pytest.approx((0.50, 0.20), abs=1e-8)
    assert texcoords[2] == pytest.approx((0.20, 0.50), abs=1e-8)
    assert metrics["projection_distance_max"] == pytest.approx(0.0, abs=1e-10)


def test_surface_projection_keeps_source_uv_seam_face_local() -> None:
    # Source vertex 0 has two UVs on two folded triangles. The same donor vertex
    # participates in matching horizontal and vertical donor faces. Face-normal
    # tie-breaking must therefore select a different source UV island per face.
    source_positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    source_texcoords = [
        (0.10, 0.10),  # vertex 0, horizontal island
        (0.40, 0.10),
        (0.10, 0.40),
        (0.80, 0.80),  # vertex 0, vertical island
        (0.80, 0.50),
        (0.50, 0.80),
    ]
    source_faces = [
        [(0, 0), (1, 1), (2, 2)],
        [(0, 3), (3, 4), (1, 5)],
    ]
    donor_positions = [
        (0.0, 0.0, 0.0),
        (0.8, 0.0, 0.0),
        (0.0, 0.8, 0.0),
        (0.0, 0.0, 0.8),
    ]

    texcoords, faces, metrics = build_surface_projected_donor_uvs(
        donor_faces=[(0, 1, 2), (0, 3, 1)],
        donor_positions=donor_positions,
        source_positions=source_positions,
        source_faces=source_faces,
        source_texcoords=source_texcoords,
        donor_to_source_vertex=[0, 1, 2, 3],
    )

    first_shared_uv = texcoords[faces[0][0][1]]
    second_shared_uv = texcoords[faces[1][0][1]]
    assert first_shared_uv == pytest.approx((0.10, 0.10), abs=1e-8)
    assert second_shared_uv == pytest.approx((0.80, 0.80), abs=1e-8)
    assert first_shared_uv != second_shared_uv
    assert metrics["seam_seed_corner_ratio"] > 0.0
    assert math.isfinite(metrics["projection_distance_p95"])


def test_surface_projection_preserves_geometric_degenerate_donor_face() -> None:
    texcoords, faces, metrics = build_surface_projected_donor_uvs(
        donor_faces=[(0, 1, 2)],
        donor_positions=[(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0)],
        source_positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        source_faces=[[(0, 0), (1, 1), (2, 2)]],
        source_texcoords=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        donor_to_source_vertex=[0, 1, 1],
    )

    assert faces == [[(0, 0), (1, 1), (2, 2)]]
    assert texcoords == pytest.approx([(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)])
    assert metrics["projected_corner_count"] == 3.0
    assert metrics["degenerate_donor_face_count"] == 1.0


def test_surface_projection_rejects_degenerate_source_face() -> None:
    with pytest.raises(SurfaceUvTransferError, match="no non-degenerate"):
        build_surface_projected_donor_uvs(
            donor_faces=[(0, 1, 2)],
            donor_positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            source_positions=[(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.0, 0.0)],
            source_faces=[[(0, 0), (1, 1), (2, 2)]],
            source_texcoords=[(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)],
            donor_to_source_vertex=[0, 1, 2],
        )
