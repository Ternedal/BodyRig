from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_canonical_bake_metadata import (  # noqa: E402
    CanonicalBakeMetadataError,
    METHOD,
    canonical_appearance_transfer,
)
from sith_canonical_texture_bake import (  # noqa: E402
    CanonicalTextureBakeError,
    bind_canonical_smplx_uvs,
    load_canonical_smplx_uv_template,
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


def _metrics(*, baked_sha: str = "b" * 64) -> dict:
    return {
        "appearance_method": "canonical-surface-bake-v1",
        "canonical_uv_template_sha256": "a" * 64,
        "source_texture_sha256": "d" * 64,
        "baked_basecolor_sha256": baked_sha,
        "bake_width": 1024.0,
        "bake_height": 1024.0,
        "bake_occupied_texel_count": 700000.0,
        "bake_occupied_ratio": 700000.0 / (1024.0 * 1024.0),
        "bake_padded_texel_ratio": 0.70,
        "bake_gutter_pixels": 8.0,
        "bake_surface_distance_p95": 0.012,
        "bake_surface_distance_max": 0.041,
    }


def test_canonical_metadata_records_three_stage_texture_authority() -> None:
    transfer = canonical_appearance_transfer(_legacy_bodyrig(), _metrics())

    assert transfer["method"] == METHOD
    assert transfer["canonicalDonorAtlas"] is True
    assert transfer["canonicalUvTemplateSha256"] == "a" * 64
    assert transfer["sourceReconstructionTextureSha256"] == "d" * 64
    assert transfer["bakedBaseColorSha256"] == "b" * 64
    assert transfer["activeBaseColorSha256"] == "c" * 64
    assert transfer["bakedBaseColorConsumedByRefinement"] is True
    assert transfer["generativeAppearanceSynthesis"] is False
    assert transfer["geometryModified"] is False
    assert transfer["bakeWidth"] == 1024
    assert transfer["bakeHeight"] == 1024


def test_canonical_metadata_rejects_bake_refinement_sha_break() -> None:
    with pytest.raises(
        CanonicalBakeMetadataError,
        match="not the byte authority consumed by refinement",
    ):
        canonical_appearance_transfer(
            _legacy_bodyrig(baked_sha="e" * 64),
            _metrics(baked_sha="b" * 64),
        )


def test_canonical_uv_template_binds_face_corner_seams_without_geometry_change(tmp_path: Path) -> None:
    template = tmp_path / "smplx_uv.obj"
    template.write_text(
        "\n".join(
            [
                "v 0 0 0",
                "v 1 0 0",
                "v 0 1 0",
                "v 0 0 1",
                "vt 0.0 0.0",
                "vt 1.0 0.0",
                "vt 0.0 1.0",
                "vt 0.8 0.8",
                "vt 0.8 0.2",
                "vt 0.2 0.8",
                "f 1/1 2/2 3/3",
                "f 1/4 4/5 2/6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    vertex_count, texcoords, geometry_faces, texture_faces = load_canonical_smplx_uv_template(template)
    bound = bind_canonical_smplx_uvs(
        donor_vertex_count=4,
        donor_faces=[(0, 1, 2), (0, 3, 1)],
        canonical_vertex_count=vertex_count,
        canonical_texcoords=texcoords,
        canonical_geometry_faces=geometry_faces,
        canonical_texture_faces=texture_faces,
    )

    assert bound == [
        [(0, 0), (1, 1), (2, 2)],
        [(0, 3), (3, 4), (1, 5)],
    ]
    assert bound[0][0][0] == bound[1][0][0] == 0
    assert bound[0][0][1] != bound[1][0][1]


def test_canonical_uv_template_rejects_donor_topology_mismatch(tmp_path: Path) -> None:
    template = tmp_path / "smplx_uv.obj"
    template.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\n"
        "f 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    vertex_count, texcoords, geometry_faces, texture_faces = load_canonical_smplx_uv_template(template)

    with pytest.raises(CanonicalTextureBakeError, match="face order"):
        bind_canonical_smplx_uvs(
            donor_vertex_count=3,
            donor_faces=[(0, 2, 1)],
            canonical_vertex_count=vertex_count,
            canonical_texcoords=texcoords,
            canonical_geometry_faces=geometry_faces,
            canonical_texture_faces=texture_faces,
        )


def test_r7_global_canonical_bake_remains_available_as_frozen_reference() -> None:
    source = (BRIDGES / "sith_canonical_texture_bake.py").read_text(encoding="utf-8")
    wrapper = (BRIDGES / "sith_smplx_vrm_fitter_gender.py").read_text(encoding="utf-8")

    assert "def bake_sith_surface_to_canonical_smplx(" in source
    assert "closest_tex(" in source
    assert "bake_sith_surface_to_canonical_smplx(" not in wrapper
    assert "R7_BAKE_RESOLUTION" not in wrapper
    assert "original_transfer(" not in wrapper
    assert "original_build_surface_projected_donor_uvs" not in wrapper
    ast.parse(source)
    ast.parse(wrapper)
