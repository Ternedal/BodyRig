from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_teacher_benchmark_plan import (
    PhotorealTeacherBenchmarkPlanError,
    build_teacher_benchmark_plan,
)


def _source(
    key: str,
    *,
    kind: str = "video",
    projection: str = "flat",
    stereo_layout: str = "mono",
    width: int = 3840,
    height: int = 2160,
    information_score: float = 100.0,
) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": key.split(":", 2)[1],
        "kind": kind,
        "resolved_path": rf"\\stash\VR_E\{key.split('/')[-1]}",
        "size_bytes": 1000,
        "sha256": ("a" if "best" in key else "b" if "other" in key else "c") * 64,
        "information_score": information_score,
        "width": width,
        "height": height,
        "projection": projection,
        "stereo_layout": stereo_layout,
    }


def _observation(key: str, index: int, coverage: list[str]) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": key.split(":", 2)[1],
        "split": "train",
        "frame_sha256": format(index % 16, "x") * 64,
        "timestamp_seconds": float(index + 1),
        "eye": "mono",
        "view_bin": "front" if index == 0 else "three-quarter-left",
        "coverage": coverage,
    }


def _teacher_input() -> dict[str, object]:
    best = "scene:best:E:/best.mp4"
    other = "scene:other:E:/other.mp4"
    vr = "scene:vr:E:/vr.mp4"
    image = "image:portrait:F:/portrait.jpg"
    observations = [
        _observation(best, 0, ["face-front", "full-body-front"]),
        _observation(best, 1, ["face-three-quarter", "full-body-three-quarter"]),
        _observation(best, 2, ["face-profile"]),
        _observation(other, 3, ["face-front", "full-body-front"]),
        _observation(vr, 4, ["face-front"]),
        _observation(image, 5, ["face-front"]),
    ]
    return {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "d" * 64,
        "training_sources": [
            _source(best, width=3840, height=2160, information_score=90.0),
            _source(other, width=7680, height=4320, information_score=200.0),
            _source(vr, projection="vr180", stereo_layout="side-by-side"),
            _source(image, kind="image", width=6000, height=4000),
        ],
        "training_observations": observations,
        "training_source_count": 4,
        "training_observation_count": len(observations),
        "held_out_evaluation_sources": [{"source_key": "scene:eval:E:/secret.mp4"}],
        "held_out_evaluation_observations": [{"frame_sha256": "e" * 64}],
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_benchmark_plan_selects_best_authorized_flat_mono_video_deterministically() -> None:
    first = build_teacher_benchmark_plan(_teacher_input())
    second = build_teacher_benchmark_plan(_teacher_input())

    assert first == second
    assert first["benchmark"] == "exavatar"
    assert first["upstream_commit"] == "d45268730c779fae4118f1a361cf9ff639bc4d1e"
    assert first["candidate_count"] == 2
    assert first["selected_source_key"] == "scene:best:E:/best.mp4"
    assert first["selected_observation_count"] == 3
    assert first["benchmark_execution_authorized"] is True
    assert first["benchmark_blockers"] == []
    assert first["selection_authority"] == "core-benchmark-scheduling-only-v1"
    assert first["photoreal_acceptance_authority"] is False
    assert first["production_activation"] is False


def test_benchmark_plan_excludes_spatial_images_and_eval_data_from_candidates() -> None:
    result = build_teacher_benchmark_plan(_teacher_input())
    candidate_keys = [item["source_key"] for item in result["candidates"]]
    encoded = str(result)

    assert candidate_keys == ["scene:best:E:/best.mp4", "scene:other:E:/other.mp4"]
    assert "scene:vr:E:/vr.mp4" not in candidate_keys
    assert "image:portrait:F:/portrait.jpg" not in candidate_keys
    assert "secret.mp4" not in encoded
    assert "e" * 64 not in encoded


def test_benchmark_plan_reports_honest_intended_utilization() -> None:
    result = build_teacher_benchmark_plan(_teacher_input())

    assert result["training_source_universe_count"] == 4
    assert result["training_observation_universe_count"] == 6
    assert result["intended_source_utilization_fraction"] == 0.25
    assert result["intended_observation_utilization_fraction"] == 0.5


def test_benchmark_plan_blocks_when_no_flat_mono_video_exists() -> None:
    value = _teacher_input()
    for source in value["training_sources"]:
        if source["kind"] == "video":
            source["projection"] = "vr180"
            source["stereo_layout"] = "side-by-side"

    result = build_teacher_benchmark_plan(value)

    assert result["candidate_count"] == 0
    assert result["selected_source_key"] is None
    assert result["selected_observations"] == []
    assert result["benchmark_execution_authorized"] is False
    assert result["benchmark_blockers"] == [
        "no authorized flat/mono training video exists in the selected appearance epoch"
    ]


def test_benchmark_plan_rejects_non_train_observation_smuggled_into_training_input() -> None:
    value = copy.deepcopy(_teacher_input())
    value["training_observations"][0]["split"] = "evaluation"

    with pytest.raises(PhotorealTeacherBenchmarkPlanError, match="not train split"):
        build_teacher_benchmark_plan(value)


def test_benchmark_plan_rejects_training_count_drift() -> None:
    value = copy.deepcopy(_teacher_input())
    value["training_observation_count"] = 999

    with pytest.raises(PhotorealTeacherBenchmarkPlanError, match="observation count mismatch"):
        build_teacher_benchmark_plan(value)


def test_benchmark_ranking_prefers_coverage_before_resolution_or_information_score() -> None:
    result = build_teacher_benchmark_plan(_teacher_input())
    assert result["candidates"][0]["source_key"] == "scene:best:E:/best.mp4"
    assert result["candidates"][1]["source_key"] == "scene:other:E:/other.mp4"
    assert result["candidates"][0]["coverage_count"] > result["candidates"][1]["coverage_count"]


def test_benchmark_plan_accepts_scan_authorized_spatial_video() -> None:
    value = copy.deepcopy(_teacher_input())
    spatial_key = "scene:vr:E:/vr.mp4"
    spatial_source = next(item for item in value["training_sources"] if item["source_key"] == spatial_key)
    spatial_observation = next(item for item in value["training_observations"] if item["source_key"] == spatial_key)
    spatial_observation["eye"] = "left"
    value["training_sources"] = [spatial_source]
    value["training_observations"] = [spatial_observation]
    value["training_source_count"] = 1
    value["training_observation_count"] = 1

    scan_plan = {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": spatial_key,
                "source_sha256": spatial_source["sha256"],
                "kind": "video",
                "split": "train",
                "group_id": spatial_source["group_id"],
                "projection": "equi",
                "stereo_layout": "side-by-side",
                "decode_mode": "spatial-deprojection-required",
                "projection_authority": {
                    "format": "bodyrig-explicit-projection-authority",
                    "version": 1,
                    "projection_type": "equi",
                    "deprojection_authority": False,
                    "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                    "equirectangular_bounds_fraction": {
                        "top": 0.0,
                        "bottom": 0.5,
                        "left": 0.0,
                        "right": 0.5,
                    },
                },
            }
        ],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    result = build_teacher_benchmark_plan(
        value,
        scan_plan=scan_plan,
        scan_plan_sha256="f" * 64,
    )

    assert result["candidate_count"] == 1
    assert result["selected_source_key"] == spatial_key
    assert result["selected_observation_count"] == 1
    assert result["benchmark_execution_authorized"] is True
    assert result["benchmark_blockers"] == []
    assert result["strategy"] == "single-authorized-video-exact-p0-replay-v2"
    assert result["selection_authority"] == "core-benchmark-scheduling-with-scan-authority-v2"
    assert result["scan_plan_sha256"] == "f" * 64
    candidate = result["candidates"][0]
    assert candidate["projection"] == "equi"
    assert candidate["stereo_layout"] == "side-by-side"
    assert candidate["decode_mode"] == "spatial-deprojection-required"
    assert candidate["normalization_action"] == "exact-authorized-deprojection"
    assert candidate["observations"][0]["eye"] == "left"


def test_benchmark_plan_scan_authority_rejects_source_sha_drift() -> None:
    value = copy.deepcopy(_teacher_input())
    spatial_key = "scene:vr:E:/vr.mp4"
    spatial_source = next(item for item in value["training_sources"] if item["source_key"] == spatial_key)
    spatial_observation = next(item for item in value["training_observations"] if item["source_key"] == spatial_key)
    spatial_observation["eye"] = "left"
    value["training_sources"] = [spatial_source]
    value["training_observations"] = [spatial_observation]
    value["training_source_count"] = 1
    value["training_observation_count"] = 1
    scan_plan = {
        "format": "bodyrig-photoreal-scan-plan",
        "version": 1,
        "performer_id": "42",
        "sources": [{
            "source_key": spatial_key,
            "source_sha256": "f" * 64,
            "kind": "video",
            "split": "train",
            "group_id": spatial_source["group_id"],
            "projection": "equi",
            "stereo_layout": "side-by-side",
            "decode_mode": "spatial-deprojection-required",
            "projection_authority": {
                "format": "bodyrig-explicit-projection-authority",
                "version": 1,
                "projection_type": "equi",
                "deprojection_authority": False,
            },
        }],
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    with pytest.raises(PhotorealTeacherBenchmarkPlanError, match="source SHA differs"):
        build_teacher_benchmark_plan(
            value,
            scan_plan=scan_plan,
            scan_plan_sha256="e" * 64,
        )
