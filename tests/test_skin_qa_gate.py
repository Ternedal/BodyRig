from __future__ import annotations

import pytest

from bodyrig.skin_qa import DONOR_GEOMETRY_AUTHORITY, DONOR_RIG_TRANSFER
from bodyrig.skin_qa_gate import ANATOMY_APPEARANCE, GateAppearanceError, _validate_transfer_authority


def _bodyrig() -> dict:
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
            "method": ANATOMY_APPEARANCE,
            "canonicalDonorAtlas": True,
            "canonicalUvTemplateSha256": "a" * 64,
            "sourceReconstructionTextureSha256": "b" * 64,
            "bakedBaseColorSha256": "c" * 64,
            "activeBaseColorSha256": "d" * 64,
            "bakeWidth": 1024,
            "bakeHeight": 1024,
            "occupiedTexelCount": 750000,
            "occupiedTexelRatio": 0.715256,
            "paddedTexelRatio": 0.78,
            "gutterPixels": 8,
            "nearestSourceSurfaceDistanceP95": 0.035545,
            "nearestSourceSurfaceDistanceMax": 0.105715,
            "sourceTextureBytesPreservedAsSeparateAuthority": True,
            "activeBaseColorUsesExactSourceBytes": False,
            "bakedBaseColorConsumedByRefinement": True,
            "sourceDerivedPbrApplied": True,
            "boundedBaseColorRefinementApplied": True,
            "generativeAppearanceSynthesis": False,
            "pbrRefinementMethod": "source-derived-pbr-v1",
            "baseColorRefinementMethod": "bounded-source-detail-v1",
            "baseColorMaxObservedChannelDelta": 0.04,
            "baseColorChannelDeltaCap": 0.05,
            "geometryModified": False,
            "anatomyRestrictedSourceSearch": True,
            "anatomyRegionCount": 6,
            "anatomyRestrictedTexelRatio": 1.0,
            "normalAwareFallback": True,
            "normalRetryTexelCount": 61000,
            "normalRetryTexelRatio": 0.061,
            "normalAlignmentMean": 0.81,
            "normalAlignmentP05": 0.554,
            "normalLowAlignmentRatio": 0.03,
            "bodyScale": 1.73,
            "anatomyTexelRatios": {
                "torso": 0.32,
                "head": 0.10,
                "left_arm": 0.12,
                "right_arm": 0.12,
                "left_leg": 0.17,
                "right_leg": 0.17,
            },
            "sourceCandidateSearchGlobal": False,
        },
    }


def test_gate_accepts_current_anatomy_bake_authority() -> None:
    method, p95, maximum = _validate_transfer_authority(_bodyrig())
    assert method == DONOR_RIG_TRANSFER
    assert p95 == 0.0
    assert maximum == 0.0


def test_gate_rejects_unversioned_or_unknown_appearance_method() -> None:
    value = _bodyrig()
    value["appearanceTransfer"]["method"] = "whatever-new-method"
    with pytest.raises(GateAppearanceError, match="appearance transfer metadata is invalid"):
        _validate_transfer_authority(value)


def test_gate_rejects_anatomy_receipt_without_full_region_coverage() -> None:
    value = _bodyrig()
    value["appearanceTransfer"]["anatomyRestrictedTexelRatio"] = 0.99
    with pytest.raises(GateAppearanceError, match="does not cover every baked texel"):
        _validate_transfer_authority(value)


def test_gate_rejects_geometry_mutation_claim() -> None:
    value = _bodyrig()
    value["appearanceTransfer"]["geometryModified"] = True
    with pytest.raises(GateAppearanceError, match="geometryModified authority is invalid"):
        _validate_transfer_authority(value)
