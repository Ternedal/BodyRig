from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_motion_preparation_authority as authority
from bodyrig.photoreal_p2_motion_preparation_authority import (
    PhotorealP2MotionPreparationAuthorityError,
    build_motion_preparation_authority,
    build_motion_preparation_authority_files,
    validate_motion_preparation_authority,
)


def _task(*, source_ref: str, source_key: str, split: str, role: str, spatial: bool) -> dict[str, object]:
    return {
        "source_ref": source_ref,
        "group_ref": f"grp-{split}",
        "split": split,
        "role": role,
        "source_key": source_key,
        "group_id": f"group-{split}",
        "resolved_path": f"/private/{split}.mp4",
        "source_sha256": ("a" if split == "train" else "b") * 64,
        "size_bytes": 123456,
        "preparation_mode": (
            "exact-authorized-deprojection-required"
            if spatial
            else "direct-exavatar-video"
        ),
        "normalization_action": (
            "exact-authorized-deprojection"
            if spatial
            else "preserve-flat-mono-video"
        ),
        "motion_parameter_extraction_required": True,
        "source_media_rehash_required": False,
        "preparation_complete": False,
    }


def _input_plan(*, spatial_driver: bool = False) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-p2-motion-input-plan",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_motion_evidence_handoff_sha256": "3" * 64,
        "p2_motion_private_index_sha256": "4" * 64,
        "p2_motion_source_selection_sha256": "5" * 64,
        "motion_driver_tasks": [
            _task(
                source_ref="src-train",
                source_key="scene:train:/private/train.mp4",
                split="train",
                role="motion-driver",
                spatial=spatial_driver,
            )
        ],
        "held_out_motion_validation_tasks": [
            _task(
                source_ref="src-eval",
                source_key="scene:eval:/private/evaluation.mp4",
                split="evaluation",
                role="held-out-motion-validation",
                spatial=False,
            )
        ],
        "motion_driver_task_count": 1,
        "held_out_motion_validation_task_count": 1,
        "exact_deprojection_task_count": 1 if spatial_driver else 0,
        "direct_flat_mono_task_count": 1 if spatial_driver else 2,
        "build_private": True,
        "source_media_rehash_required": False,
        "source_media_rehash_performed": False,
        "motion_parameter_extraction_required": True,
        "motion_fitting_backend": "pinned-exavatar-fitting-v1",
        "motion_fitting_camera_mode": "virtual",
        "motion_input_plan_ready": True,
        "p2_motion_input_authorized": True,
        "motion_input_preparation_execution_authorized": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "p2_motion_input_plan_sha256": "6" * 64,
    }


def _equi_authority() -> dict[str, object]:
    return {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.0,
            "right": 0.0,
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


def _scan_source(*, split: str, spatial: bool) -> dict[str, object]:
    source_key = (
        "scene:train:/private/train.mp4"
        if split == "train"
        else "scene:eval:/private/evaluation.mp4"
    )
    if spatial:
        projection = "equi"
        stereo = "side-by-side"
        decode_mode = "spatial-deprojection-required"
        projection_authority = _equi_authority()
        samples = [
            {"timestamp_seconds": 1.0, "eye": "left"},
            {"timestamp_seconds": 1.0, "eye": "right"},
        ]
    else:
        projection = "flat"
        stereo = "mono"
        decode_mode = "rectilinear-mono"
        projection_authority = None
        samples = [{"timestamp_seconds": 1.0, "eye": "mono"}]
    return {
        "source_key": source_key,
        "source_sha256": ("a" if split == "train" else "b") * 64,
        "resolved_path": f"/private/{split}.mp4",
        "kind": "video",
        "split": split,
        "group_id": f"group-{split}",
        "source_binding": "scene-performer",
        "performer_count": 1,
        "projection": projection,
        "projection_authority": projection_authority,
        "stereo_layout": stereo,
        "decode_mode": decode_mode,
        "sample_count": len(samples),
        "samples": samples,
        "identity_bootstrap_eligible": split == "train",
    }


def _scan_plan(*, spatial_driver: bool = False) -> dict[str, object]:
    sources = [
        _scan_source(split="train", spatial=spatial_driver),
        _scan_source(split="evaluation", spatial=False),
    ]
    return {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "fixture",
        "strategy": "uniform-midpoint-scout-v1",
        "target_video_interval_seconds": 10.0,
        "minimum_video_scout_samples": 12,
        "maximum_video_scout_samples": 120,
        "source_count": len(sources),
        "planned_observation_count": sum(int(item["sample_count"]) for item in sources),
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "identity_bootstrap_source_count": 1,
        "identity_bootstrap_group_count": 1,
        "sources": sources,
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "frame_analyzer_required": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _patch_input_validation(monkeypatch: pytest.MonkeyPatch, plan: dict[str, object]) -> None:
    monkeypatch.setattr(authority, "validate_motion_input_plan", lambda *_args, **_kwargs: plan)


def test_motion_preparation_authority_grants_preparation_only(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _input_plan()
    scan = _scan_plan()
    _patch_input_validation(monkeypatch, plan)

    result = build_motion_preparation_authority(
        {},
        {},
        {},
        plan,
        scan,
        scan_plan_file_sha256="9" * 64,
    )

    assert result["motion_input_preparation_execution_authorized"] is True
    assert result["p2_animation_execution_authorized"] is False
    assert result["p2_animated_teacher_acceptance_authority"] is False
    assert result["quest_distillation_authorized"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert result["source_media_rehash_required"] is False
    assert result["direct_flat_mono_binding_count"] == 2
    assert result["equirectangular_deprojection_binding_count"] == 0


def test_motion_preparation_authority_reuses_exact_spatial_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan(spatial_driver=True)
    scan = _scan_plan(spatial_driver=True)
    _patch_input_validation(monkeypatch, plan)

    result = build_motion_preparation_authority(
        {},
        {},
        {},
        plan,
        scan,
        scan_plan_file_sha256="9" * 64,
    )

    binding = result["motion_driver_bindings"][0]
    assert binding["normalization_action"] == "exact-authorized-deprojection"
    assert binding["scan_projection"] == "equi"
    assert binding["scan_stereo_layout"] == "side-by-side"
    assert binding["projection_authority"] == _equi_authority()
    assert isinstance(binding["projection_authority_sha256"], str)
    assert len(binding["projection_authority_sha256"]) == 64
    assert result["equirectangular_deprojection_binding_count"] == 1


def test_motion_preparation_authority_rejects_spatial_source_without_projection_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan(spatial_driver=True)
    scan = _scan_plan(spatial_driver=True)
    scan["sources"][0]["projection_authority"] = None
    _patch_input_validation(monkeypatch, plan)

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="lacks exact P0 projection authority",
    ):
        build_motion_preparation_authority(
            {},
            {},
            {},
            plan,
            scan,
            scan_plan_file_sha256="9" * 64,
        )


def test_motion_preparation_authority_rejects_private_path_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan()
    scan = _scan_plan()
    scan["sources"][0]["resolved_path"] = "/private/substituted.mp4"
    _patch_input_validation(monkeypatch, plan)

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="binding mismatch: resolved_path",
    ):
        build_motion_preparation_authority(
            {},
            {},
            {},
            plan,
            scan,
            scan_plan_file_sha256="9" * 64,
        )


def test_motion_preparation_authority_rejects_non_equi_spatial_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan(spatial_driver=True)
    scan = _scan_plan(spatial_driver=True)
    scan["sources"][0]["projection"] = "mshp"
    scan["sources"][0]["projection_authority"]["projection_type"] = "mshp"
    _patch_input_validation(monkeypatch, plan)

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="not exact equirectangular P0 authority",
    ):
        build_motion_preparation_authority(
            {},
            {},
            {},
            plan,
            scan,
            scan_plan_file_sha256="9" * 64,
        )


def test_motion_preparation_authority_validator_rejects_resealed_animation_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan()
    scan = _scan_plan()
    _patch_input_validation(monkeypatch, plan)
    result = build_motion_preparation_authority(
        {},
        {},
        {},
        plan,
        scan,
        scan_plan_file_sha256="9" * 64,
    )

    result["p2_animation_execution_authorized"] = True
    result["p2_motion_preparation_authority_sha256"] = authority._digest(
        result,
        omit="p2_motion_preparation_authority_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="authority mismatch: p2_animation_execution_authorized",
    ):
        validate_motion_preparation_authority(
            result,
            handoff={},
            private_index={},
            selection={},
            input_plan=plan,
            scan_plan=scan,
            scan_plan_file_sha256="9" * 64,
        )


def test_motion_preparation_authority_rejects_boolean_scan_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _input_plan()
    scan = _scan_plan()
    scan["version"] = True
    _patch_input_validation(monkeypatch, plan)

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="format/version mismatch",
    ):
        build_motion_preparation_authority(
            {},
            {},
            {},
            plan,
            scan,
            scan_plan_file_sha256="9" * 64,
        )


def test_motion_preparation_authority_file_reuse_is_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _input_plan()
    scan = _scan_plan()
    _patch_input_validation(monkeypatch, plan)

    handoff_path = tmp_path / "handoff.json"
    private_path = tmp_path / "private.json"
    selection_path = tmp_path / "selection.json"
    input_path = tmp_path / "input.json"
    scan_path = tmp_path / "scan.json"
    output_path = tmp_path / "authority.json"
    for path, value in (
        (handoff_path, {}),
        (private_path, {}),
        (selection_path, {}),
        (input_path, plan),
        (scan_path, scan),
    ):
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    first = build_motion_preparation_authority_files(
        handoff_path,
        private_path,
        selection_path,
        input_path,
        scan_path,
        output_path,
    )
    second = build_motion_preparation_authority_files(
        handoff_path,
        private_path,
        selection_path,
        input_path,
        scan_path,
        output_path,
        reuse_existing=True,
    )
    assert first == second

    tampered = copy.deepcopy(first)
    tampered["production_activation"] = True
    output_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2MotionPreparationAuthorityError,
        match="differs from canonical current state",
    ):
        build_motion_preparation_authority_files(
            handoff_path,
            private_path,
            selection_path,
            input_path,
            scan_path,
            output_path,
            reuse_existing=True,
        )
