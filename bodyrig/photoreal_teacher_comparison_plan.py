from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_teacher_benchmark_plan import (
    PhotorealTeacherBenchmarkPlanError,
    build_teacher_benchmark_plan,
)
from .photoreal_teacher_benchmark_registry import build_benchmark_registry

FORMAT = "bodyrig-photoreal-teacher-comparison-plan"
VERSION = 1


class PhotorealTeacherComparisonPlanError(ValueError):
    pass


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_teacher_comparison_plan(teacher_input: Mapping[str, Any]) -> dict[str, Any]:
    try:
        source_plan = build_teacher_benchmark_plan(teacher_input)
    except PhotorealTeacherBenchmarkPlanError as exc:
        raise PhotorealTeacherComparisonPlanError(str(exc)) from exc

    registry = build_benchmark_registry()
    candidate_exists = source_plan.get("benchmark_execution_authorized") is True
    selected_source_key = source_plan.get("selected_source_key")
    selected_source_sha = source_plan.get("selected_source_sha256")
    selected_observations = list(source_plan.get("selected_observations") or [])

    benchmarks: list[dict[str, Any]] = []
    for entry in registry["benchmarks"]:
        adapter_status = str(entry["teacher_adapter_status"])
        adapter_implemented = adapter_status == "implemented"
        blockers: list[str] = []
        if not candidate_exists:
            blockers.extend(str(item) for item in source_plan.get("benchmark_blockers") or [])
        if not adapter_implemented:
            blockers.append(f"teacher adapter is not implemented: {entry['benchmark']} ({adapter_status})")
        if entry["license_posture"] == "research-noncommercial-only":
            blockers.append("benchmark is research/noncommercial only and can never become a production dependency without separate permission")

        benchmarks.append(
            {
                "benchmark": entry["benchmark"],
                "priority": entry["priority"],
                "upstream_repository": entry["upstream_repository"],
                "upstream_ref": entry["upstream_ref"],
                "representation": entry["representation"],
                "teacher_adapter_status": adapter_status,
                "license_posture": entry["license_posture"],
                "production_dependency_authorized": False,
                "same_selected_source_key": selected_source_key,
                "same_selected_source_sha256": selected_source_sha,
                "same_selected_observations": selected_observations,
                "same_selected_observation_count": len(selected_observations),
                "held_out_evaluation_disclosed": False,
                "source_candidate_eligible": candidate_exists,
                "execution_ready_now": candidate_exists and adapter_implemented,
                "execution_blockers": sorted(set(blockers)),
                "photoreal_acceptance_authority": False,
                "human_visual_acceptance_required": True,
                "production_activation": False,
            }
        )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": source_plan["performer_id"],
        "selected_epoch_id": source_plan["selected_epoch_id"],
        "teacher_input_sha256": source_plan["teacher_input_sha256"],
        "benchmark_registry_sha256": registry["benchmark_registry_sha256"],
        "source_selection_strategy": source_plan["strategy"],
        "selected_source_key": selected_source_key,
        "selected_source_sha256": selected_source_sha,
        "selected_observation_count": len(selected_observations),
        "selected_observations": selected_observations,
        "benchmark_count": len(benchmarks),
        "benchmarks": benchmarks,
        "comparison_policy": registry["comparison_policy"],
        "all_benchmarks_share_identical_training_subset": True,
        "held_out_evaluation_is_external_to_all_teacher_processes": True,
        "benchmark_success_is_photoreal_acceptance": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["comparison_plan_sha256"] = _digest(result)
    return result


def build_teacher_comparison_plan_files(teacher_input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(teacher_input_path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherComparisonPlanError(f"teacher input is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherComparisonPlanError("teacher input must be a JSON object")
    result = build_teacher_comparison_plan(value)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherComparisonPlanError(f"teacher comparison plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
