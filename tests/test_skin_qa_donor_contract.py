from __future__ import annotations

import pytest

from bodyrig.skin_qa import (
    DONOR_APPEARANCE_TRANSFER,
    DONOR_GEOMETRY_AUTHORITY,
    DONOR_RIG_TRANSFER,
    LEGACY_RIG_TRANSFER,
    SkinQaError,
    _validate_transfer_authority,
)


def test_legacy_transfer_authority_stays_supported() -> None:
    method, p95, maximum = _validate_transfer_authority(
        {
            "rigTransfer": {
                "method": LEGACY_RIG_TRANSFER,
                "nearestDistanceP95": 0.012,
                "nearestDistanceMax": 0.031,
            }
        }
    )
    assert method == LEGACY_RIG_TRANSFER
    assert p95 == 0.012
    assert maximum == 0.031


def _donor_bodyrig() -> dict[str, object]:
    return {
        "rigTransfer": {
            "method": DONOR_RIG_TRANSFER,
            "nearestDistanceP95": 0.0,
            "nearestDistanceMax": 0.0,
        },
        "geometryAuthority": {
            "method": DONOR_GEOMETRY_AUTHORITY,
            "sourceMeshGeometryUsed": False,
            "stableTopology": True,
        },
        "appearanceTransfer": {
            "method": DONOR_APPEARANCE_TRANSFER,
            "sourceSurfaceDistanceP95": 0.021,
            "sourceSurfaceDistanceMax": 0.084,
            "multiUvSourceVertexRatio": 0.14,
            "sourceTextureBytesPreserved": True,
            "geometryModified": False,
        },
    }


def test_donor_transfer_authority_requires_explicit_geometry_boundary() -> None:
    method, p95, maximum = _validate_transfer_authority(_donor_bodyrig())
    assert method == DONOR_RIG_TRANSFER
    assert p95 == 0.0
    assert maximum == 0.0


def test_donor_transfer_rejects_source_mesh_geometry_claim() -> None:
    bodyrig = _donor_bodyrig()
    geometry = dict(bodyrig["geometryAuthority"])  # type: ignore[arg-type]
    geometry["sourceMeshGeometryUsed"] = True
    bodyrig["geometryAuthority"] = geometry
    with pytest.raises(SkinQaError, match="geometry authority"):
        _validate_transfer_authority(bodyrig)


def test_donor_transfer_rejects_fake_nearest_lbs_distance() -> None:
    bodyrig = _donor_bodyrig()
    transfer = dict(bodyrig["rigTransfer"])  # type: ignore[arg-type]
    transfer["nearestDistanceP95"] = 0.01
    bodyrig["rigTransfer"] = transfer
    with pytest.raises(SkinQaError, match="must not claim nearest-transfer"):
        _validate_transfer_authority(bodyrig)


def test_donor_transfer_rejects_unbounded_multi_uv_ratio() -> None:
    bodyrig = _donor_bodyrig()
    appearance = dict(bodyrig["appearanceTransfer"])  # type: ignore[arg-type]
    appearance["multiUvSourceVertexRatio"] = 1.1
    bodyrig["appearanceTransfer"] = appearance
    with pytest.raises(SkinQaError, match="multi-UV ratio"):
        _validate_transfer_authority(bodyrig)
