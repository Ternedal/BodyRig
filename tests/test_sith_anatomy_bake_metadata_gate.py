from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_anatomy_bake_metadata import (  # noqa: E402
    AnatomyBakeMetadataError,
    anatomy_appearance_transfer,
    replace_with_anatomy_bake_metadata,
)
from sith_pbr_material import _read_glb, _write_glb  # noqa: E402


def _bodyrig() -> dict:
    return {
        "geometryAuthority": {
            "method": "smplx-fitted-donor-topology-v1",
            "sourceMeshGeometryUsed": False,
            "stableTopology": True,
        },
        "appearanceTransfer": {
            "method": "sith-source-local-triangle-barycentric-uv-v1",
            "sourceBaseColorSha256": "b" * 64,
            "activeBaseColorSha256": "c" * 64,
            "sourceDerivedPbrApplied": True,
            "boundedBaseColorRefinementApplied": True,
            "pbrRefinementMethod": "source-derived-normal-roughness-v1",
            "baseColorRefinementMethod": "bounded-source-detail-v1",
            "baseColorMaxObservedChannelDelta": 0.05,
            "baseColorChannelDeltaCap": 0.08,
        },
    }


def _metrics() -> dict:
    return {
        "appearance_method": "canonical-anatomy-normal-bake-v2",
        "canonical_uv_template_sha256": "a" * 64,
        "source_texture_sha256": "d" * 64,
        "baked_basecolor_sha256": "b" * 64,
        "bake_width": 1024.0,
        "bake_height": 1024.0,
        "bake_occupied_texel_count": 700000.0,
        "bake_occupied_ratio": 0.667572,
        "bake_padded_texel_ratio": 0.70,
        "bake_gutter_pixels": 8.0,
        "bake_surface_distance_p95": 0.012,
        "bake_surface_distance_max": 0.041,
        "anatomy_region_count": 6.0,
        "anatomy_restricted_texel_ratio": 1.0,
        "normal_retry_texel_count": 14000.0,
        "normal_retry_texel_ratio": 0.02,
        "normal_alignment_mean": 0.91,
        "normal_alignment_p05": 0.55,
        "normal_low_alignment_ratio": 0.01,
        "body_scale": 2.0,
        "region_torso_texel_ratio": 0.30,
        "region_head_texel_ratio": 0.10,
        "region_left_arm_texel_ratio": 0.10,
        "region_right_arm_texel_ratio": 0.10,
        "region_left_leg_texel_ratio": 0.20,
        "region_right_leg_texel_ratio": 0.20,
    }


def test_anatomy_metadata_rejects_partial_restriction_coverage() -> None:
    metrics = _metrics()
    metrics["anatomy_restricted_texel_ratio"] = 0.999

    with pytest.raises(AnatomyBakeMetadataError, match="does not cover every baked texel"):
        anatomy_appearance_transfer(_bodyrig(), metrics)


def test_anatomy_metadata_rejects_string_normal_metric() -> None:
    metrics = _metrics()
    metrics["normal_alignment_mean"] = "0.91"

    with pytest.raises(AnatomyBakeMetadataError, match="normal alignment mean is invalid"):
        anatomy_appearance_transfer(_bodyrig(), metrics)


def test_anatomy_metadata_embeds_fail_closed_component_receipts() -> None:
    document = {
        "buffers": [{"byteLength": 0}],
        "extras": {"bodyrig": _bodyrig()},
    }
    avatar = _write_glb(document, b"")

    updated = replace_with_anatomy_bake_metadata(avatar, mapping_metrics=_metrics())
    parsed, _binary = _read_glb(updated)
    bodyrig = parsed["extras"]["bodyrig"]
    receipt = bodyrig["fidelityComponents"]
    face = bodyrig["faceSecondaryFidelity"]

    assert receipt["highFidelityReady"] is False
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False
    assert receipt["components"]["body_anatomy"] == "not-evaluated"
    assert receipt["components"]["skin_appearance"] == "partial"
    assert receipt["components"]["hair"] == "missing"
    assert receipt["components"]["eyes"] == "missing"
    assert receipt["components"]["face_secondary"] == "missing"

    assert face["format"] == "bodyrig-face-secondary-fidelity"
    assert face["version"] == 1
    assert face["components"] == {
        "eyebrow_appearance": "not-evaluated",
        "lip_boundary": "not-evaluated",
        "mouth_interior": "missing",
        "teeth": "missing",
        "eyelashes": "missing",
    }
    assert face["faceSecondaryReady"] is False
    assert face["semanticVertexMapAuthority"] == "unavailable"
    assert face["humanReviewRequired"] is True
    assert face["productionReady"] is False


def test_anatomy_metadata_rejects_preexisting_face_secondary_receipt() -> None:
    bodyrig = _bodyrig()
    bodyrig["faceSecondaryFidelity"] = {"unexpected": True}
    document = {
        "buffers": [{"byteLength": 0}],
        "extras": {"bodyrig": bodyrig},
    }
    avatar = _write_glb(document, b"")

    with pytest.raises(AnatomyBakeMetadataError, match="face-secondary receipt is already present"):
        replace_with_anatomy_bake_metadata(avatar, mapping_metrics=_metrics())
