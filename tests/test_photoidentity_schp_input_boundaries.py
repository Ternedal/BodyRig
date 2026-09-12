from __future__ import annotations

import pytest

from bodyrig.photoidentity_schp_detail import (
    PhotoIdentitySchpDetailError,
    _finite,
    _normalize_map,
    analyze_schp_detail,
)


def _seg() -> list[list[object]]:
    return [[0 for _ in range(512)] for _ in range(512)]


def _observation(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "target_confidence": 0.95,
        "face_visibility": 0.95,
        "full_body_visibility": 0.95,
        "sharpness": 0.95,
        "occlusion": 0.05,
    }
    value.update(changes)
    return value


def test_finite_normalizes_arbitrary_precision_overflow() -> None:
    with pytest.raises(PhotoIdentitySchpDetailError, match="must be in 0..1"):
        _finite(10**400, label="target confidence")


def test_finite_preserves_inclusive_numeric_boundaries() -> None:
    assert _finite(0, label="quality") == 0.0
    assert _finite(1.0, label="quality") == 1.0


def test_segmentation_label_overflow_fails_closed() -> None:
    segmentation = _seg()
    segmentation[0][0] = float("inf")

    with pytest.raises(PhotoIdentitySchpDetailError, match="non-integer label"):
        _normalize_map(segmentation)


def test_analyze_schp_detail_normalizes_huge_observation_value() -> None:
    with pytest.raises(PhotoIdentitySchpDetailError, match="observation sharpness must be in 0..1"):
        analyze_schp_detail(
            _seg(),
            scene_id="scene-overflow",
            observation=_observation(sharpness=10**400),
            source_width=1920,
            source_height=1080,
        )
