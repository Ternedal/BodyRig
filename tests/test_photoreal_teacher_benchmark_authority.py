from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_teacher_benchmark_authority import (
    build_teacher_benchmark_plan_files_strict,
)
from bodyrig.photoreal_teacher_benchmark_plan import PhotorealTeacherBenchmarkPlanError


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source(*, key: str, group: str, path: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "kind": "video",
        "resolved_path": path,
        "size_bytes": 1000,
        "sha256": sha * 64,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "flat",
        "stereo_layout": "mono",
    }


def _observation(*, key: str, group: str, split: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "split": split,
        "frame_sha256": sha * 64,
        "timestamp_seconds": 1.0,
        "eye": "mono",
        "view_bin": "front",
        "coverage": ["face-front", "full-body-front"],
    }


def _teacher_input() -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "selected_epoch_id": "epoch-a",
        "appearance_epoch_selection_sha256": "a" * 64,
        "identity_bank_sha256": "b" * 64,
        "identity_calibration_sha256": "c" * 64,
        "analyzer_model_set_sha256": "d" * 64,
        "training_sources": [
            _source(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                path=r"\\stash\VR_E\train.mp4",
                sha="e",
            )
        ],
        "held_out_evaluation_sources": [
            _source(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                path=r"\\stash\VR_E\eval.mp4",
                sha="f",
            )
        ],
        "training_observations": [
            _observation(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                split="train",
                sha="1",
            )
        ],
        "held_out_evaluation_observations": [
            _observation(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                split="evaluation",
                sha="2",
            )
        ],
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "held_out_view_coverage_observed": ["face-front", "full-body-front"],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 1,
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["teacher_input_sha256"] = _digest(value)
    return value


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _reseal(value: dict[str, object]) -> None:
    value.pop("teacher_input_sha256", None)
    value["teacher_input_sha256"] = _digest(value)


def test_strict_benchmark_plan_accepts_hash_bound_teacher_input(tmp_path: Path) -> None:
    teacher_input = tmp_path / "teacher-input.json"
    output = tmp_path / "benchmark-plan.json"
    _write(teacher_input, _teacher_input())

    result = build_teacher_benchmark_plan_files_strict(teacher_input, output)

    assert output.is_file()
    assert result["benchmark"] == "exavatar"
    assert result["selected_source_key"] == "scene:train:E:/train.mp4"
    assert result["benchmark_execution_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_strict_benchmark_plan_rejects_boolean_v1_even_when_resealed(tmp_path: Path) -> None:
    value = _teacher_input()
    value["version"] = True
    _reseal(value)
    teacher_input = tmp_path / "teacher-input.json"
    _write(teacher_input, value)

    with pytest.raises(PhotorealTeacherBenchmarkPlanError, match="format/version mismatch"):
        build_teacher_benchmark_plan_files_strict(teacher_input, tmp_path / "benchmark-plan.json")


def test_strict_benchmark_plan_rejects_stale_teacher_input_digest(tmp_path: Path) -> None:
    value = _teacher_input()
    value["training_sources"][0]["resolved_path"] = r"\\stash\VR_E\substituted.mp4"
    teacher_input = tmp_path / "teacher-input.json"
    _write(teacher_input, value)

    with pytest.raises(PhotorealTeacherBenchmarkPlanError, match="SHA-256 does not match manifest content"):
        build_teacher_benchmark_plan_files_strict(teacher_input, tmp_path / "benchmark-plan.json")
