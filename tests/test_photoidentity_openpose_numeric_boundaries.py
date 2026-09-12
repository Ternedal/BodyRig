from __future__ import annotations

import pytest

from bodyrig.photoidentity_openpose_detail import (
    PhotoIdentityOpenPoseDetailError,
    _finite,
    _triples,
    merge_best_claims,
)


def test_finite_huge_integer_fails_with_domain_error() -> None:
    with pytest.raises(PhotoIdentityOpenPoseDetailError, match="must be in"):
        _finite(10**400, label="observation sharpness")


def test_openpose_triples_reject_boolean_component() -> None:
    with pytest.raises(PhotoIdentityOpenPoseDetailError, match="non-numeric"):
        _triples([0.0, 0.0, True], label="probe", expected_points=1)


def test_openpose_triples_huge_integer_fails_with_domain_error() -> None:
    with pytest.raises(PhotoIdentityOpenPoseDetailError, match="invalid coordinates/confidence"):
        _triples([10**400, 0.0, 0.9], label="probe", expected_points=1)


def test_openpose_triples_preserve_ordinary_numeric_values() -> None:
    assert _triples([10, 20.5, 1], label="probe", expected_points=1) == [(10.0, 20.5, 1.0)]


def test_merge_best_claims_rejects_overflowing_existing_quality() -> None:
    destination = {
        "hands": [
            {
                "scene_id": "scene-1",
                "quality": 10**400,
                "source_derived": True,
                "adapter": "openpose-body25-face-hand-detail",
                "revision": "1",
            }
        ]
    }
    incoming = {
        "hands": [
            {
                "scene_id": "scene-1",
                "quality": 0.8,
                "source_derived": True,
                "adapter": "openpose-body25-face-hand-detail",
                "revision": "1",
            }
        ]
    }

    with pytest.raises(PhotoIdentityOpenPoseDetailError, match="existing quality"):
        merge_best_claims(destination, incoming)
