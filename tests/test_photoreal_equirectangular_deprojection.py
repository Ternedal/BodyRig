from __future__ import annotations

import numpy as np
import pytest

from bodyrig.photoreal_equirectangular_deprojection import (
    PhotorealEquirectangularDeprojectionError,
    build_equirectangular_remap,
    build_equirectangular_viewports,
)


def _authority(
    *,
    left: float = 0.0,
    right: float = 0.0,
    top: float = 0.0,
    bottom: float = 0.0,
    authority_format: str = "bodyrig-spherical-v2-projection-authority",
):
    return {
        "format": authority_format,
        "version": 1,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 17.0, "pitch": -4.0, "roll": 2.0},
        "equirectangular_bounds_fraction": {
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
        },
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_encoding": None,
        "mesh_projection_payload_bytes": None,
        "deprojection_authority": False,
    }


@pytest.mark.parametrize(
    "authority_format",
    [
        "bodyrig-spherical-v2-projection-authority",
        "bodyrig-explicit-projection-authority",
    ],
)
def test_accepts_supported_projection_authority_provenance(authority_format: str) -> None:
    views = build_equirectangular_viewports(_authority(authority_format=authority_format))
    assert views


def test_rejects_unknown_projection_authority_provenance() -> None:
    with pytest.raises(PhotorealEquirectangularDeprojectionError, match="format/version mismatch"):
        build_equirectangular_viewports(_authority(authority_format="bodyrig-unknown-projection-authority"))


def test_rejects_boolean_authority_version() -> None:
    authority = _authority()
    authority["version"] = True
    with pytest.raises(PhotorealEquirectangularDeprojectionError, match="format/version mismatch"):
        build_equirectangular_viewports(authority)


def test_full_sphere_uses_bounded_eight_viewport_grid() -> None:
    views = build_equirectangular_viewports(_authority())
    assert len(views) == 8
    assert [view["viewport_id"] for view in views] == [f"v{index:02d}" for index in range(8)]
    assert max(float(view["horizontal_fov_degrees"]) for view in views) <= 110.0
    assert max(float(view["vertical_fov_degrees"]) for view in views) <= 110.0


def test_vr180_like_crop_reduces_viewport_count_without_guessing_projection() -> None:
    views = build_equirectangular_viewports(_authority(left=0.25, right=0.25))
    assert len(views) == 4
    yaws = sorted({float(view["yaw_degrees"]) for view in views})
    assert yaws[0] >= -90.0
    assert yaws[-1] <= 90.0


def test_central_ray_maps_to_center_of_authoritative_crop() -> None:
    authority = _authority(left=0.25, right=0.25, top=0.25, bottom=0.25)
    viewport = {
        "viewport_id": "v00",
        "yaw_degrees": 0.0,
        "pitch_degrees": 0.0,
        "horizontal_fov_degrees": 90.0,
        "vertical_fov_degrees": 90.0,
    }
    map_x, map_y = build_equirectangular_remap(
        np,
        image_width=401,
        image_height=201,
        projection_authority=authority,
        viewport=viewport,
        output_size=65,
    )
    assert map_x.shape == (65, 65)
    assert map_y.shape == (65, 65)
    assert float(map_x[32, 32]) == pytest.approx(200.0, abs=1e-4)
    assert float(map_y[32, 32]) == pytest.approx(100.0, abs=1e-4)


def test_crop_masks_rays_outside_authoritative_projection() -> None:
    authority = _authority(left=0.25, right=0.25, top=0.25, bottom=0.25)
    viewport = {
        "viewport_id": "v00",
        "yaw_degrees": 85.0,
        "pitch_degrees": 0.0,
        "horizontal_fov_degrees": 110.0,
        "vertical_fov_degrees": 90.0,
    }
    map_x, map_y = build_equirectangular_remap(
        np,
        image_width=401,
        image_height=201,
        projection_authority=authority,
        viewport=viewport,
        output_size=65,
    )
    assert np.any(map_x < 0.0)
    assert np.any(map_y < 0.0)


def test_rejects_missing_or_crossed_projection_authority() -> None:
    with pytest.raises(PhotorealEquirectangularDeprojectionError, match="authority"):
        build_equirectangular_viewports({})
    crossed = _authority()
    crossed["deprojection_authority"] = True
    with pytest.raises(PhotorealEquirectangularDeprojectionError, match="crossed"):
        build_equirectangular_viewports(crossed)
