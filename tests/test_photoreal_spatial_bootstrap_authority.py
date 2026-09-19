from __future__ import annotations

from bodyrig.photoreal_scan_plan import build_scan_plan


def _source(*, key: str, group: str, projection: str, stereo_layout: str) -> dict[str, object]:
    return {
        "kind": "video",
        "source_id": key,
        "group_id": group,
        "path": key.split(":", 2)[-1],
        "information_score": 100.0,
        "projection": projection,
        "stereo_layout": stereo_layout,
        "width": 7680 if stereo_layout == "side-by-side" else 3840,
        "height": 3840 if stereo_layout == "side-by-side" else 2160,
        "duration_seconds": 60.0,
        "frame_rate": 60.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }


def test_train_spatial_source_is_retained_but_never_identity_bootstrap_authority() -> None:
    flat = _source(
        key="scene:flat:E:/flat.mp4",
        group="scene:flat",
        projection="flat",
        stereo_layout="mono",
    )
    spatial = _source(
        key="scene:vr:E:/vr180.mp4",
        group="scene:vr",
        projection="vr180",
        stereo_layout="side-by-side",
    )
    evaluation = _source(
        key="scene:eval:E:/eval.mp4",
        group="scene:eval",
        projection="flat",
        stereo_layout="mono",
    )
    plan = {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [flat, spatial],
        "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    receipt_sources = []
    for index, item in enumerate([flat, spatial, evaluation], start=1):
        receipt_sources.append(
            {
                "kind": "video",
                "source_id": str(item["source_id"]).split(":", 2)[1],
                "source_key": item["source_id"],
                "resolved_path": rf"\\stash\VR_E\source-{index}.mp4",
                "sha256": format(index, "x") * 64,
            }
        )
    receipt = {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": receipt_sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    result = build_scan_plan(plan, receipt)
    by_key = {item["source_key"]: item for item in result["sources"]}

    assert by_key[flat["source_id"]]["identity_bootstrap_eligible"] is True
    assert by_key[spatial["source_id"]]["decode_mode"] == "spatial-deprojection-required"
    assert by_key[spatial["source_id"]]["identity_bootstrap_eligible"] is False
    assert spatial["source_id"] in by_key


def test_train_authority_bound_equi_source_can_bootstrap_after_deprojection() -> None:
    spatial = _source(
        key="scene:vr:E:/vr180.mp4",
        group="scene:vr",
        projection="equi",
        stereo_layout="side-by-side",
    )
    spatial["projection_authority"] = {
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
    second = _source(
        key="scene:vr2:E:/vr180-2.mp4",
        group="scene:vr2",
        projection="equi",
        stereo_layout="side-by-side",
    )
    second["projection_authority"] = dict(spatial["projection_authority"])
    evaluation = _source(
        key="scene:eval:E:/eval.mp4",
        group="scene:eval",
        projection="flat",
        stereo_layout="mono",
    )
    plan = {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [spatial, second],
        "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    receipt_sources = []
    for index, item in enumerate([spatial, second, evaluation], start=1):
        receipt_sources.append(
            {
                "kind": "video",
                "source_id": str(item["source_id"]).split(":", 2)[1],
                "source_key": item["source_id"],
                "resolved_path": rf"\\stash\VR_E\authority-{index}.mp4",
                "sha256": format(index, "x") * 64,
            }
        )
    receipt = {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": receipt_sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    result = build_scan_plan(plan, receipt)
    by_key = {item["source_key"]: item for item in result["sources"]}

    assert by_key[spatial["source_id"]]["decode_mode"] == "spatial-deprojection-required"
    assert by_key[spatial["source_id"]]["identity_bootstrap_eligible"] is True
    assert by_key[second["source_id"]]["identity_bootstrap_eligible"] is True
    assert result["identity_bootstrap_source_count"] == 2
    assert result["identity_bootstrap_group_count"] == 2
