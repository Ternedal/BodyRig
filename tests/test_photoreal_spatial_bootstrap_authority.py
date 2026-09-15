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
