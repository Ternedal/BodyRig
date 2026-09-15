from __future__ import annotations

import copy

from bodyrig.photoreal_teacher_comparison_plan import build_teacher_comparison_plan
from bodyrig.photoreal_teacher_benchmark_registry import build_benchmark_registry


def _teacher_input() -> dict[str, object]:
    source = "scene:best:E:/best.mp4"
    eval_source = "scene:eval:E:/held-out.mp4"
    observations = [
        {
            "source_key": source,
            "group_id": "best",
            "split": "train",
            "frame_sha256": (format(index + 1, "x") * 64),
            "timestamp_seconds": float(index + 1),
            "eye": "mono",
            "view_bin": "front" if index == 0 else "three-quarter-left",
            "coverage": coverage,
        }
        for index, coverage in enumerate(
            (["face-front", "full-body-front"], ["face-three-quarter", "full-body-three-quarter"], ["face-profile"])
        )
    ]
    return {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "d" * 64,
        "training_sources": [
            {
                "source_key": source,
                "group_id": "best",
                "kind": "video",
                "resolved_path": r"\\stash\VR_E\best.mp4",
                "size_bytes": 1000,
                "sha256": "a" * 64,
                "information_score": 100.0,
                "width": 3840,
                "height": 2160,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "training_observations": observations,
        "training_source_count": 1,
        "training_observation_count": len(observations),
        "held_out_evaluation_sources": [{"source_key": eval_source}],
        "held_out_evaluation_observations": [{"source_key": eval_source, "frame_sha256": "e" * 64}],
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_registry_pins_three_independent_teacher_comparators() -> None:
    registry = build_benchmark_registry()
    ids = [entry["benchmark"] for entry in registry["benchmarks"]]
    assert ids == ["exavatar", "gaussianavatar", "splattingavatar"]
    assert registry["benchmark_count"] == 3
    assert all(entry["production_dependency_authorized"] is False for entry in registry["benchmarks"])
    assert registry["benchmark_success_is_photoreal_acceptance"] is False


def test_comparison_plan_forces_identical_training_subset_across_benchmarks() -> None:
    result = build_teacher_comparison_plan(_teacher_input())
    assert result["benchmark_count"] == 3
    assert result["all_benchmarks_share_identical_training_subset"] is True
    assert result["held_out_evaluation_is_external_to_all_teacher_processes"] is True
    assert result["selected_source_key"] == "scene:best:E:/best.mp4"
    expected = result["selected_observations"]
    assert expected
    for benchmark in result["benchmarks"]:
        assert benchmark["same_selected_source_key"] == result["selected_source_key"]
        assert benchmark["same_selected_source_sha256"] == result["selected_source_sha256"]
        assert benchmark["same_selected_observations"] == expected
        assert benchmark["held_out_evaluation_disclosed"] is False
        assert benchmark["photoreal_acceptance_authority"] is False
        assert benchmark["production_activation"] is False


def test_only_implemented_exavatar_adapter_is_execution_ready_now() -> None:
    result = build_teacher_comparison_plan(_teacher_input())
    by_id = {entry["benchmark"]: entry for entry in result["benchmarks"]}
    assert by_id["exavatar"]["execution_ready_now"] is True
    assert by_id["gaussianavatar"]["execution_ready_now"] is False
    assert by_id["splattingavatar"]["execution_ready_now"] is False
    assert "teacher adapter is not implemented" in by_id["gaussianavatar"]["execution_blockers"][0]
    assert any("research/noncommercial" in blocker for blocker in by_id["splattingavatar"]["execution_blockers"])


def test_comparison_plan_never_serializes_held_out_paths_or_hashes() -> None:
    value = _teacher_input()
    result = build_teacher_comparison_plan(value)
    encoded = str(result)
    assert "held-out.mp4" not in encoded
    assert "e" * 64 not in encoded


def test_no_source_candidate_blocks_every_benchmark_without_waiver() -> None:
    value = copy.deepcopy(_teacher_input())
    value["training_sources"][0]["projection"] = "vr180"
    value["training_sources"][0]["stereo_layout"] = "side-by-side"
    result = build_teacher_comparison_plan(value)
    assert result["selected_source_key"] is None
    assert all(entry["source_candidate_eligible"] is False for entry in result["benchmarks"])
    assert all(entry["execution_ready_now"] is False for entry in result["benchmarks"])
