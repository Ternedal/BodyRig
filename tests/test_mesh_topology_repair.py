from __future__ import annotations

from bodyrig.mesh_topology_repair import _encode_indices, _is_repair_candidate


def test_repair_candidate_removes_physically_large_triangle() -> None:
    assert _is_repair_candidate(
        max_edge=0.30,
        altitude=0.20,
        aspect=1.5,
        body_scale=2.0,
    )


def test_repair_candidate_removes_long_sliver() -> None:
    assert _is_repair_candidate(
        max_edge=0.10,
        altitude=0.001,
        aspect=100.0,
        body_scale=2.0,
    )


def test_repair_candidate_keeps_tiny_local_sliver() -> None:
    assert not _is_repair_candidate(
        max_edge=0.01,
        altitude=0.00001,
        aspect=1000.0,
        body_scale=2.0,
    )


def test_index_encoder_preserves_unsigned_component_width() -> None:
    assert _encode_indices(5121, [0, 1, 255]) == bytes([0, 1, 255])
    assert len(_encode_indices(5123, [0, 1, 65535])) == 6
    assert len(_encode_indices(5125, [0, 1, 100000])) == 12
