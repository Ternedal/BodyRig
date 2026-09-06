from __future__ import annotations

import bodyrig.skin_qa as skin_qa


def _legacy_direct_donor_bodyrig() -> dict[str, object]:
    return {
        "rigTransfer": {
            "method": skin_qa.DONOR_RIG_TRANSFER,
            "nearestDistanceP95": 0.0,
            "nearestDistanceMax": 0.0,
        },
        "geometryAuthority": {
            "method": skin_qa.DONOR_GEOMETRY_AUTHORITY,
            "sourceMeshGeometryUsed": False,
            "stableTopology": True,
        },
        "appearanceTransfer": {
            "method": skin_qa.DONOR_APPEARANCE_TRANSFER,
            "sourceTextureBytesPreserved": True,
            "geometryModified": False,
            "sourceSurfaceDistanceP95": 0.01,
            "sourceSurfaceDistanceMax": 0.02,
            "multiUvSourceVertexRatio": 0.1,
        },
    }


def test_legacy_direct_donor_appearance_survives_current_validator_patch() -> None:
    bodyrig = _legacy_direct_donor_bodyrig()
    with skin_qa._PATCH_LOCK:
        original = skin_qa.legacy._validate_transfer_authority
        skin_qa.legacy._validate_transfer_authority = skin_qa._validate_transfer_authority
        try:
            result = skin_qa._validate_transfer_authority(bodyrig)
        finally:
            skin_qa.legacy._validate_transfer_authority = original

    assert result == (skin_qa.DONOR_RIG_TRANSFER, 0.0, 0.0)
