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
