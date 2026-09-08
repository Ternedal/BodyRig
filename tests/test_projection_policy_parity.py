from __future__ import annotations

import pytest

from bodyrig.projection_safety import is_projection_ambiguous_geometry
from bodyrig.stash_source import _has_projection_ambiguous_geometry


@pytest.mark.parametrize(
    "width,height",
    [
        (1920, 1080),
        (2560, 1440),
        (2879, 1440),
        (2880, 1440),
        (3840, 2160),
        (4096, 2160),
        (4212, 2160),
        (4213, 2160),
        (4320, 2160),
        (5120, 2560),
        (7168, 3584),
        (8192, 4096),
    ],
)
def test_package_projection_policy_matches_stash_ranking(width: int, height: int) -> None:
    assert is_projection_ambiguous_geometry(width, height) == _has_projection_ambiguous_geometry(
        width=width,
        height=height,
    )


def test_known_real_projection_geometries_remain_rejected_and_flat_16x9_remains_safe() -> None:
    assert not is_projection_ambiguous_geometry(3840, 2160)
    assert is_projection_ambiguous_geometry(8192, 4096)
    assert is_projection_ambiguous_geometry(5120, 2560)
    assert is_projection_ambiguous_geometry(4320, 2160)
