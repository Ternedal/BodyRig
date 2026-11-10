from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_teacher_authority import validate_teacher_input_document
from .photoreal_teacher_benchmark_plan import (
    PhotorealTeacherBenchmarkPlanError,
    build_teacher_benchmark_plan,
)
from .photoreal_teacher_runner import PhotorealTeacherRunnerError
from . import hashing
from . import json_io


def _strict_json_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    return json_io.read_json_object(
        source,
        error=PhotorealTeacherBenchmarkPlanError,
        unreadable=f"photoreal teacher input is unreadable: {source}",
        not_object="photoreal teacher input must be a JSON object",
    )


def validate_teacher_benchmark_plan_files_strict(
    teacher_input_path: str | Path,
    benchmark_plan_path: str | Path,
    *,
    scan_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    teacher_input = _read_json(teacher_input_path)
    try:
        validated = validate_teacher_input_document(teacher_input)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealTeacherBenchmarkPlanError(
            f"teacher input authority validation failed: {exc}"
        ) from exc
    scan_plan = None
    scan_sha = None
    if scan_plan_path is not None:
        scan_path = Path(scan_plan_path).expanduser().resolve()
        scan_plan = _read_json(scan_path)
        scan_sha = hashing.sha256_file(scan_path)
    expected = (
        build_teacher_benchmark_plan(validated)
        if scan_plan is None
        else build_teacher_benchmark_plan(validated, scan_plan=scan_plan, scan_plan_sha256=scan_sha)
    )
    plan = _read_json(benchmark_plan_path)
    if not _strict_json_equal(plan, expected):
        raise PhotorealTeacherBenchmarkPlanError(
            "existing teacher benchmark plan does not match strict current teacher input"
        )
    return plan


def build_teacher_benchmark_plan_files_strict(
    teacher_input_path: str | Path,
    output_path: str | Path,
    *,
    scan_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    teacher_input = _read_json(teacher_input_path)
    try:
        validated = validate_teacher_input_document(teacher_input)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealTeacherBenchmarkPlanError(
            f"teacher input authority validation failed: {exc}"
        ) from exc

    scan_plan = None
    scan_sha = None
    if scan_plan_path is not None:
        scan_path = Path(scan_plan_path).expanduser().resolve()
        scan_plan = _read_json(scan_path)
        scan_sha = hashing.sha256_file(scan_path)

    result = (
        build_teacher_benchmark_plan(validated)
        if scan_plan is None
        else build_teacher_benchmark_plan(validated, scan_plan=scan_plan, scan_plan_sha256=scan_sha)
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherBenchmarkPlanError(
            f"teacher benchmark plan already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
