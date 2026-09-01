from __future__ import annotations

import pytest

from bodyrig.bridges.sith_donor_topology import (
    DonorTopologyError,
    build_donor_faces,
    canonical_source_uv_map,
)


def test_canonical_source_uv_map_uses_frequency_then_lowest_uv() -> None:
    mapping, metrics = canonical_source_uv_map(
        source_vertex_count=4,
        texcoord_count=6,
        faces=[
            [(0, 4), (1, 1), (2, 2)],
            [(0, 3), (2, 2), (3, 5)],
            [(0, 4), (3, 5), (1, 1)],
        ],
    )
    assert mapping == {0: 4, 1: 1, 2: 2, 3: 5}
    assert metrics["textured_source_vertex_count"] == 4.0
    assert metrics["multi_uv_source_vertex_count"] == 1.0
    assert metrics["multi_uv_source_vertex_ratio"] == 0.25


def test_canonical_source_uv_map_tie_breaks_deterministically() -> None:
    mapping, _ = canonical_source_uv_map(
        source_vertex_count=3,
        texcoord_count=5,
        faces=[
            [(0, 4), (1, 1), (2, 2)],
            [(0, 3), (1, 1), (2, 2)],
        ],
    )
    assert mapping[0] == 3


def test_build_donor_faces_keeps_donor_vertex_indices_and_source_uvs() -> None:
    faces = build_donor_faces(
        donor_faces=[(0, 1, 2), (2, 1, 3)],
        donor_vertex_count=4,
        donor_to_source_vertex=[7, 6, 5, 4],
        source_uv_map={4: 40, 5: 50, 6: 60, 7: 70},
    )
    assert faces == [
        [(0, 70), (1, 60), (2, 50)],
        [(2, 50), (1, 60), (3, 40)],
    ]


def test_build_donor_faces_fails_on_untextured_mapping() -> None:
    with pytest.raises(DonorTopologyError, match="untextured"):
        build_donor_faces(
            donor_faces=[(0, 1, 2)],
            donor_vertex_count=3,
            donor_to_source_vertex=[0, 1, 2],
            source_uv_map={0: 0, 1: 1},
        )


def test_build_donor_faces_fails_on_degenerate_donor_face() -> None:
    with pytest.raises(DonorTopologyError, match="degenerate"):
        build_donor_faces(
            donor_faces=[(0, 1, 1)],
            donor_vertex_count=3,
            donor_to_source_vertex=[0, 1, 2],
            source_uv_map={0: 0, 1: 1, 2: 2},
        )
