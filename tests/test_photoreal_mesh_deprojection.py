from __future__ import annotations

import copy

import numpy as np
import pytest

from bodyrig.photoreal_mesh_deprojection import (
    PhotorealMeshDeprojectionError,
    _selected_mesh,
    _triangles,
    build_mesh_remap,
    build_mesh_viewports,
)


def _square_mesh(*, index_type: int = 0) -> dict[str, object]:
    indices = [0, 1, 2, 0, 2, 3]
    if index_type == 1:
        indices = [0, 1, 3, 2]
    elif index_type == 2:
        indices = [0, 1, 2, 3]
    return {
        "coordinate_count": 3,
        "vertex_count": 4,
        "vertex_list_count": 1,
        "index_count": len(indices),
        "texture_ids": [0],
        "index_types": [index_type],
        "vertices": [
            (-1.0, -1.0, -1.0, 0.0, 0.0),
            (1.0, -1.0, -1.0, 1.0, 0.0),
            (1.0, 1.0, -1.0, 1.0, 1.0),
            (-1.0, 1.0, -1.0, 0.0, 1.0),
        ],
        "vertex_lists": [{"texture_id": 0, "index_type": index_type, "indices": indices}],
        "trailing_extension_bytes": 0,
    }


def _geometry(*, meshes: list[dict[str, object]] | None = None) -> dict[str, object]:
    values = meshes or [_square_mesh()]
    return {
        "format": "bodyrig-spherical-v2-mesh-geometry",
        "version": 1,
        "encoding": "raw ",
        "encoded_payload_bytes": 128,
        "decompressed_payload_bytes": 128,
        "decompressed_payload_sha256": "a" * 64,
        "mesh_projection_crc32": "1a2b3c4d",
        "mesh_projection_crc32_computed": "1a2b3c4d",
        "mesh_projection_crc32_matches": True,
        "mesh_count": len(values),
        "total_vertex_count": sum(int(item["vertex_count"]) for item in values),
        "total_index_count": sum(int(item["index_count"]) for item in values),
        "texture_ids": [0],
        "index_types": sorted({int(value) for item in values for value in item["index_types"]}),
        "unknown_box_types": [],
        "meshes": values,
        "materialized": True,
        "render_authority": False,
        "production_activation": False,
        "projection_data_version": 0,
        "projection_data_flags": 0,
    }


def _authority(geometry: dict[str, object]) -> dict[str, object]:
    return {
        "format": "bodyrig-spherical-v2-projection-authority",
        "version": 1,
        "projection_type": "mshp",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": None,
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": geometry["mesh_projection_crc32"],
        "mesh_projection_encoding": geometry["encoding"],
        "mesh_projection_payload_bytes": geometry["encoded_payload_bytes"],
        "mesh_projection_geometry_sha256": geometry["decompressed_payload_sha256"],
        "mesh_projection_mesh_count": geometry["mesh_count"],
        "mesh_projection_total_vertex_count": geometry["total_vertex_count"],
        "mesh_projection_total_index_count": geometry["total_index_count"],
        "mesh_projection_texture_ids": geometry["texture_ids"],
        "mesh_projection_index_types": geometry["index_types"],
        "mesh_projection_unknown_box_types": geometry["unknown_box_types"],
        "deprojection_authority": False,
    }


def test_square_mesh_builds_one_forward_tangent_viewport() -> None:
    viewports = build_mesh_viewports(_square_mesh())
    assert len(viewports) == 1
    assert abs(float(viewports[0]["yaw_degrees"])) < 1e-6
    assert abs(float(viewports[0]["pitch_degrees"])) < 1e-6
    assert 89.0 < float(viewports[0]["horizontal_fov_degrees"]) <= 90.0
    assert 70.0 < float(viewports[0]["vertical_fov_degrees"]) < 71.0


def test_square_mesh_remap_maps_center_to_texture_center_and_flips_open_gl_v() -> None:
    viewport = build_mesh_viewports(_square_mesh())[0]
    map_x, map_y, coverage = build_mesh_remap(
        np,
        image_width=201,
        image_height=101,
        mesh=_square_mesh(),
        viewport=viewport,
        output_size=128,
    )
    assert coverage > 0.98
    assert abs(float(map_x[64, 64]) - 100.0) < 2.0
    assert abs(float(map_y[64, 64]) - 50.0) < 2.0
    assert float(map_y[8, 64]) < float(map_y[119, 64])


@pytest.mark.parametrize("index_type", [0, 1, 2])
def test_supported_primitive_lists_expand_to_triangles(index_type: int) -> None:
    triangles = _triangles(_square_mesh(index_type=index_type))
    assert len(triangles) >= 2
    assert all(len(set(triangle)) == 3 for triangle in triangles)


def test_reserved_texture_only_mesh_cannot_create_video_measurement_viewports() -> None:
    mesh = _square_mesh()
    mesh["vertex_lists"] = [{"texture_id": 1, "index_type": 0, "indices": [0, 1, 2]}]
    with pytest.raises(PhotorealMeshDeprojectionError, match="video texture"):
        build_mesh_viewports(mesh)


def test_two_mesh_projection_selects_left_and_right_exactly() -> None:
    left = _square_mesh()
    right = copy.deepcopy(left)
    right["vertices"][0] = (-0.5, -1.0, -1.0, 0.0, 0.0)
    geometry = _geometry(meshes=[left, right])
    assert _selected_mesh(geometry, "left") is left
    assert _selected_mesh(geometry, "right") is right
    with pytest.raises(PhotorealMeshDeprojectionError, match="left or right"):
        _selected_mesh(geometry, "mono")


def test_mesh_projection_authority_mismatch_fails_closed() -> None:
    from bodyrig.photoreal_mesh_deprojection import _authority as validate_authority

    geometry = _geometry()
    authority = _authority(geometry)
    validate_authority(authority, geometry)
    authority["mesh_projection_geometry_sha256"] = "b" * 64
    with pytest.raises(PhotorealMeshDeprojectionError, match="disagrees"):
        validate_authority(authority, geometry)
