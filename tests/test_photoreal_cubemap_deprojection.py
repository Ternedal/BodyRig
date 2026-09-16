from __future__ import annotations

import numpy as np
import pytest

from bodyrig.photoreal_cubemap_deprojection import (
    PhotorealCubemapDeprojectionError,
    build_cubemap_remap,
    build_cubemap_viewports,
)


def _authority(*, layout: int = 0, padding: int = 0) -> dict[str, object]:
    return {
        "format": "bodyrig-spherical-v2-projection-authority",
        "version": 1,
        "projection_type": "cbmp",
        "cubemap_layout": layout,
        "cubemap_padding_pixels": padding,
        "deprojection_authority": False,
    }


def _center_mapping(viewport_id: str, *, padding: int = 0) -> tuple[float, float]:
    viewport = next(item for item in build_cubemap_viewports() if item["viewport_id"] == viewport_id)
    map_x, map_y = build_cubemap_remap(
        np,
        image_width=300,
        image_height=200,
        projection_authority=_authority(padding=padding),
        viewport=viewport,
        output_size=65,
    )
    return float(map_x[32, 32]), float(map_y[32, 32])


@pytest.mark.parametrize(
    ("viewport_id", "expected_x", "expected_y"),
    [
        ("right", 49.5, 49.5),
        ("left", 149.5, 49.5),
        ("up", 249.5, 49.5),
        ("down", 49.5, 149.5),
        ("front", 149.5, 149.5),
        ("back", 249.5, 149.5),
    ],
)
def test_layout_zero_maps_cardinal_rays_to_v2_face_centres(
    viewport_id: str,
    expected_x: float,
    expected_y: float,
) -> None:
    x, y = _center_mapping(viewport_id)
    assert x == pytest.approx(expected_x, abs=0.05)
    assert y == pytest.approx(expected_y, abs=0.05)


def test_v2_pole_face_orientation_is_not_ffmpeg_default() -> None:
    up_forward = {
        "viewport_id": "up-forward",
        "yaw_degrees": 0.0,
        "pitch_degrees": 60.0,
        "horizontal_fov_degrees": 60.0,
        "vertical_fov_degrees": 60.0,
    }
    down_forward = {
        "viewport_id": "down-forward",
        "yaw_degrees": 0.0,
        "pitch_degrees": -60.0,
        "horizontal_fov_degrees": 60.0,
        "vertical_fov_degrees": 60.0,
    }
    up_x, up_y = build_cubemap_remap(
        np,
        image_width=300,
        image_height=200,
        projection_authority=_authority(),
        viewport=up_forward,
        output_size=65,
    )
    down_x, down_y = build_cubemap_remap(
        np,
        image_width=300,
        image_height=200,
        projection_authority=_authority(),
        viewport=down_forward,
        output_size=65,
    )

    # V2 layout 0 specifies up top = forward and down top = back. The centre
    # rays here point forward while remaining inside the pole faces, so forward
    # must land in the upper half of UP and lower half of DOWN.
    assert 200.0 <= float(up_x[32, 32]) < 300.0
    assert float(up_y[32, 32]) < 49.5
    assert 0.0 <= float(down_x[32, 32]) < 100.0
    assert float(down_y[32, 32]) > 149.5


def test_fixed_pixel_padding_moves_samples_inward_within_face() -> None:
    viewport = {
        "viewport_id": "front-right",
        "yaw_degrees": 40.0,
        "pitch_degrees": 0.0,
        "horizontal_fov_degrees": 60.0,
        "vertical_fov_degrees": 60.0,
    }
    no_pad_x, no_pad_y = build_cubemap_remap(
        np,
        image_width=300,
        image_height=200,
        projection_authority=_authority(padding=0),
        viewport=viewport,
        output_size=65,
    )
    padded_x, padded_y = build_cubemap_remap(
        np,
        image_width=300,
        image_height=200,
        projection_authority=_authority(padding=10),
        viewport=viewport,
        output_size=65,
    )
    face_center_x = 149.5
    face_center_y = 149.5
    assert abs(float(padded_x[32, 32]) - face_center_x) < abs(float(no_pad_x[32, 32]) - face_center_x)
    assert abs(float(padded_y[32, 32]) - face_center_y) <= abs(float(no_pad_y[32, 32]) - face_center_y) + 1e-6


def test_rejects_unknown_layout_and_impossible_padding() -> None:
    viewport = build_cubemap_viewports()[0]
    with pytest.raises(PhotorealCubemapDeprojectionError, match="unsupported Spherical V2 cubemap layout"):
        build_cubemap_remap(
            np,
            image_width=300,
            image_height=200,
            projection_authority=_authority(layout=1),
            viewport=viewport,
            output_size=65,
        )
    with pytest.raises(PhotorealCubemapDeprojectionError, match="padding consumes"):
        build_cubemap_remap(
            np,
            image_width=300,
            image_height=200,
            projection_authority=_authority(padding=100),
            viewport=viewport,
            output_size=65,
        )
