from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_anatomy_bake_metadata import (  # noqa: E402
    METHOD,
    anatomy_appearance_transfer,
)
from sith_anatomy_texture_bake import (  # noqa: E402
    AnatomyTextureBakeError,
    REGION_INDEX,
    appearance_joint_region,
    normal_candidate_score,
    source_face_region_memberships,
)


def _legacy_bodyrig(*, baked_sha: str = "b" * 64) -> dict:
    return {
        "geometryAuthority": {
            "method": "smplx-fitted-donor-topology-v1",
            "sourceMeshGeometryUsed": False,
            "stableTopology": True,
        },
        "appearanceTransfer": {
            "method": "sith-source-local-triangle-barycentric-uv-v1",
            "sourceBaseColorSha256": baked_sha,
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
        "bake_occupied_ratio": 700000.0 / (1024.0 * 1024.0),
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


@pytest.mark.parametrize(
    ("joint", "region"),
    [
        ("pelvis", "torso"),
        ("spine3", "torso"),
        ("neck", "head"),
        ("head", "head"),
        ("jaw", "head"),
        ("left_eye", "head"),
        ("right_eye", "head"),
        ("left_collar", "left_arm"),
        ("left_shoulder", "left_arm"),
        ("left_elbow", "left_arm"),
        ("left_wrist", "left_arm"),
        ("left_index2", "left_arm"),
        ("right_collar", "right_arm"),
        ("right_thumb3", "right_arm"),
        ("left_hip", "left_leg"),
        ("left_knee", "left_leg"),
        ("left_ankle", "left_leg"),
        ("left_foot", "left_leg"),
        ("right_hip", "right_leg"),
        ("right_knee", "right_leg"),
        ("right_ankle", "right_leg"),
        ("right_foot", "right_leg"),
    ],
)
def test_joint_names_map_to_anatomical_appearance_regions(joint: str, region: str) -> None:
    assert appearance_joint_region(joint) == region


def test_source_faces_keep_only_regions_exposed_by_their_vertices() -> None:
    memberships = source_face_region_memberships(
        [
            REGION_INDEX["torso"],
            REGION_INDEX["left_arm"],
            REGION_INDEX["left_arm"],
            REGION_INDEX["right_leg"],
        ],
        [(0, 1, 2), (0, 2, 3)],
    )

    assert memberships == [
        {REGION_INDEX["torso"], REGION_INDEX["left_arm"]},
        {REGION_INDEX["torso"], REGION_INDEX["left_arm"], REGION_INDEX["right_leg"]},
    ]


def test_source_face_region_membership_rejects_invalid_indices() -> None:
    with pytest.raises(AnatomyTextureBakeError, match="outside range"):
        source_face_region_memberships([REGION_INDEX["torso"]], [(0, 1, 0)])


def test_normal_alignment_can_beat_a_closer_opposite_surface() -> None:
    aligned = normal_candidate_score(distance=0.020, alignment=1.0, body_scale=2.0, offset=0.0)
    opposite = normal_candidate_score(distance=0.005, alignment=-1.0, body_scale=2.0, offset=0.0)

    assert aligned < opposite


def test_normal_candidate_score_rejects_nonfinite_input() -> None:
    with pytest.raises(AnatomyTextureBakeError, match="non-finite"):
        normal_candidate_score(distance=float("nan"), alignment=1.0, body_scale=2.0, offset=0.0)


def test_anatomy_metadata_keeps_canonical_texture_authority_and_records_restrictions() -> None:
    transfer = anatomy_appearance_transfer(_legacy_bodyrig(), _metrics())

    assert transfer["method"] == METHOD
    assert transfer["canonicalDonorAtlas"] is True
    assert transfer["sourceReconstructionTextureSha256"] == "d" * 64
    assert transfer["bakedBaseColorSha256"] == "b" * 64
    assert transfer["activeBaseColorSha256"] == "c" * 64
    assert transfer["anatomyRestrictedSourceSearch"] is True
    assert transfer["anatomyRegionCount"] == 6
    assert transfer["anatomyRestrictedTexelRatio"] == 1.0
    assert transfer["normalAwareFallback"] is True
    assert transfer["sourceCandidateSearchGlobal"] is False
    assert transfer["generativeAppearanceSynthesis"] is False
    assert transfer["geometryModified"] is False


def test_active_wrapper_routes_r8_without_executing_r7_or_legacy_projectors() -> None:
    source = (BRIDGES / "sith_smplx_vrm_fitter_gender.py").read_text(encoding="utf-8")

    assert "R8_BAKE_RESOLUTION = 1024" in source
    assert "import sith_anatomy_texture_bake as anatomy_bake" in source
    assert "bake_sith_surface_to_anatomy_canonical_smplx(" in source
    assert "model_dir=resolved_model_dir" in source
    assert "gender=gender" in source
    assert "replace_with_anatomy_bake_metadata(" in source
    assert "bake_sith_surface_to_canonical_smplx(" not in source
    assert "canonical_bake.BAKE_RESOLUTION" not in source
    assert 'compatibility_metrics["projection_distance_p95"] = 0.0' in source
    assert 'compatibility_metrics["projection_distance_max"] = 0.0' in source
    assert "original_build_surface_projected_donor_uvs" not in source
    ast.parse(source)
