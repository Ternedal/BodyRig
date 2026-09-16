from __future__ import annotations

import copy

import pytest

import bodyrig.photoreal_projection_authority as authority
from bodyrig.photoreal_projection_authority import PhotorealProjectionAuthorityError, resolve_v2_projection_ambiguity


def _plan(projection: str) -> dict[str, object]:
    train = {
        "kind": "video",
        "source_id": "scene:s1:E:/tagged.mp4",
        "group_id": "scene:s1",
        "path": "E:/tagged.mp4",
        "information_score": 100.0,
        "projection": projection,
        "stereo_layout": "side-by-side",
        "width": 7680,
        "height": 3840,
        "duration_seconds": 60.0,
        "frame_rate": 60.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }
    evaluation = copy.deepcopy(train)
    evaluation.update({
        "source_id": "scene:s2:E:/flat.mp4",
        "group_id": "scene:s2",
        "path": "E:/flat.mp4",
        "projection": "flat",
        "stereo_layout": "mono",
    })
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [train],
        "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "kind": item["kind"],
                "source_key": item["source_id"],
                "resolved_path": f"/verified/{split}.mp4",
                "sha256": ("a" if split == "train" else "b") * 64,
            }
            for split in ("train", "evaluation")
            for item in plan[split]
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _equi_probe() -> dict[str, object]:
    return {
        "probe_status": "parsed-isobmff",
        "st3d_present": True,
        "st3d_version": 0,
        "st3d_flags": 0,
        "stereo_mode": "left-right",
        "sv3d_present": True,
        "proj_present": True,
        "projection_type": "equi",
        "prhd_present": True,
        "prhd_version": 0,
        "prhd_flags": 0,
        "projection_pose_yaw_degrees": 0.0,
        "projection_pose_pitch_degrees": 0.0,
        "projection_pose_roll_degrees": 0.0,
        "projection_data_version": 0,
        "projection_data_flags": 0,
        "equirectangular_bounds_valid": True,
        "equirectangular_bounds_fraction": {"top": 0.0, "bottom": 0.0, "left": 0.25, "right": 0.25},
    }


@pytest.mark.parametrize("hint", ["projection-ambiguous-2to1", "vr180", "vr360", "equirectangular"])
def test_every_spatial_hint_is_replaced_by_container_authority(monkeypatch: pytest.MonkeyPatch, hint: str) -> None:
    plan = _plan(hint)
    receipt = _receipt(plan)
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _equi_probe())
    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1
    assert plan["train"][0]["projection"] == hint
    assert resolved["train"][0]["projection"] == "equi"
    assert resolved["train"][0]["projection_authority"]["projection_type"] == "equi"


def test_spatial_tag_without_v2_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan("vr180")
    receipt = _receipt(plan)
    monkeypatch.setattr(
        authority,
        "probe_isobmff_file",
        lambda _path: {"probe_status": "parsed-isobmff", "sv3d_present": False, "proj_present": False},
    )
    with pytest.raises(PhotorealProjectionAuthorityError, match="lacks Spherical V2"):
        resolve_v2_projection_ambiguity(plan, receipt)
