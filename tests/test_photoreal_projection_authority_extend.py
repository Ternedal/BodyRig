from __future__ import annotations

import copy

import pytest

import bodyrig.photoreal_explicit_projection_authority as explicit
from bodyrig.photoreal_projection_authority_extend import (
    PhotorealProjectionAuthorityExtensionError,
    extend_verified_vr180_manifest,
)


def _authority() -> dict[str, object]:
    return {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.25,
            "right": 0.25,
        },
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_encoding": None,
        "mesh_projection_payload_bytes": None,
        "mesh_projection_geometry_sha256": None,
        "mesh_projection_mesh_count": None,
        "mesh_projection_total_vertex_count": None,
        "mesh_projection_total_index_count": None,
        "mesh_projection_texture_ids": None,
        "mesh_projection_index_types": None,
        "mesh_projection_unknown_box_types": None,
        "deprojection_authority": False,
    }


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [
            {
                "kind": "video",
                "source_id": "scene:old:E:/old.mp4",
                "group_id": "scene:old",
                "projection": "vr180",
                "stereo_layout": "mono",
            },
            {
                "kind": "video",
                "source_id": "scene:new:E:/new.mp4",
                "group_id": "scene:new",
                "projection": "projection-ambiguous-2to1",
                "stereo_layout": "unknown",
            },
        ],
        "evaluation": [
            {
                "kind": "video",
                "source_id": "scene:flat:E:/flat.mp4",
                "group_id": "scene:flat",
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
        "sources": [
            {
                "kind": "video",
                "source_key": "scene:old:E:/old.mp4",
                "resolved_path": "E:/old.mp4",
                "sha256": "a" * 64,
            },
            {
                "kind": "video",
                "source_key": "scene:new:E:/new.mp4",
                "resolved_path": "E:/new.mp4",
                "sha256": "b" * 64,
            },
            {
                "kind": "video",
                "source_key": "scene:flat:E:/flat.mp4",
                "resolved_path": "E:/flat.mp4",
                "sha256": "c" * 64,
            },
        ],
    }


def _prior() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-explicit-projection-authority",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:old:E:/old.mp4",
                "source_sha256": "a" * 64,
                "stereo_layout": "side-by-side",
                "authority_basis": "operator-verified",
                "projection_authority": _authority(),
            }
        ],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


@pytest.fixture(autouse=True)
def _no_embedded_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        explicit,
        "probe_isobmff_file",
        lambda _path: {
            "probe_status": "parsed-isobmff",
            "sv3d_present": False,
            "proj_present": False,
            "spherical_v1_present": False,
            "st3d_present": False,
        },
    )


def test_extension_preserves_prior_entry_and_adds_only_missing_source() -> None:
    prior = _prior()

    manifest, missing = extend_verified_vr180_manifest(
        _plan(),
        _receipt(),
        prior,
        new_stereo_layout="side-by-side",
        operator_verified_new_sources=True,
    )

    assert missing == ["scene:new:E:/new.mp4"]
    assert len(manifest["sources"]) == 2
    old = next(item for item in manifest["sources"] if item["source_key"] == "scene:old:E:/old.mp4")
    new = next(item for item in manifest["sources"] if item["source_key"] == "scene:new:E:/new.mp4")
    assert old == prior["sources"][0]
    assert new["source_sha256"] == "b" * 64
    assert new["stereo_layout"] == "side-by-side"
    assert new["authority_basis"] == "operator-verified"
    assert new["projection_authority"]["projection_type"] == "equi"
    assert manifest["production_activation"] is False


def test_extension_requires_explicit_attestation_for_missing_sources() -> None:
    with pytest.raises(PhotorealProjectionAuthorityExtensionError, match="explicit operator verification"):
        extend_verified_vr180_manifest(
            _plan(),
            _receipt(),
            _prior(),
            new_stereo_layout="side-by-side",
            operator_verified_new_sources=False,
        )


def test_extension_rejects_prior_sha_drift_against_new_receipt() -> None:
    receipt = _receipt()
    receipt["sources"][0]["sha256"] = "d" * 64

    with pytest.raises(PhotorealProjectionAuthorityExtensionError, match="no longer validates"):
        extend_verified_vr180_manifest(
            _plan(),
            receipt,
            _prior(),
            new_stereo_layout="side-by-side",
            operator_verified_new_sources=True,
        )


def test_extension_rejects_prior_source_that_is_no_longer_spatial() -> None:
    plan = copy.deepcopy(_plan())
    plan["train"][0]["projection"] = "flat"
    plan["train"][0]["stereo_layout"] = "mono"

    with pytest.raises(PhotorealProjectionAuthorityExtensionError, match="no longer classified as spatial"):
        extend_verified_vr180_manifest(
            plan,
            _receipt(),
            _prior(),
            new_stereo_layout="side-by-side",
            operator_verified_new_sources=True,
        )
