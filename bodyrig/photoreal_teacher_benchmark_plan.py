from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

INPUT_FORMAT = "bodyrig-photoreal-teacher-input"
INPUT_VERSION = 1
FORMAT = "bodyrig-photoreal-teacher-benchmark-plan"
VERSION = 1
BENCHMARK = "exavatar"
STRATEGY = "single-flat-mono-video-coverage-ranking-v1"
UPSTREAM_REPOSITORY = "https://github.com/mks0601/ExAvatar_RELEASE"
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"


class PhotorealTeacherBenchmarkPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherBenchmarkPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid")
    return result


def _count(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} cannot be negative")
    return result


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid") from exc
    if not math.isfinite(result) or result < 0:
        raise PhotorealTeacherBenchmarkPlanError(f"{label} is invalid")
    return result


def _timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PhotorealTeacherBenchmarkPlanError("training observation timestamp is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealTeacherBenchmarkPlanError("training observation timestamp is invalid") from exc
    if not math.isfinite(result) or result < 0:
        raise PhotorealTeacherBenchmarkPlanError("training observation timestamp is invalid")
    return round(result, 6)


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_input(value: Mapping[str, Any]) -> tuple[str, str, str]:
    if value.get("format") != INPUT_FORMAT or value.get("version") != INPUT_VERSION:
        raise PhotorealTeacherBenchmarkPlanError("teacher input format/version mismatch")
    if value.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherBenchmarkPlanError("teacher input does not authorize benchmark training")
    if value.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise PhotorealTeacherBenchmarkPlanError("teacher input evaluation isolation policy is invalid")
    if value.get("held_out_view_coverage_missing") != []:
        raise PhotorealTeacherBenchmarkPlanError("teacher input held-out view coverage is incomplete")
    if value.get("photoreal_acceptance_authority") is not False or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherBenchmarkPlanError("teacher input photoreal/human authority boundary is invalid")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealTeacherBenchmarkPlanError("teacher input build/runtime authority boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealTeacherBenchmarkPlanError("teacher input crossed production authority")
    return (
        _text(value.get("performer_id"), label="teacher performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="teacher selected epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256"),
    )


def _training_sources(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_sources = value.get("training_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise PhotorealTeacherBenchmarkPlanError("teacher input contains no training sources")
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherBenchmarkPlanError("teacher training source is invalid")
        source_key = _text(raw.get("source_key"), label="training source key")
        if source_key in result:
            raise PhotorealTeacherBenchmarkPlanError("teacher input repeats training source key")
        result[source_key] = {
            "source_key": source_key,
            "source_sha256": _sha(raw.get("sha256"), label="training source SHA-256"),
            "resolved_path": _text(raw.get("resolved_path"), label="training source resolved path", maximum=32768),
            "group_id": _text(raw.get("group_id"), label="training source group id"),
            "kind": _text(raw.get("kind"), label="training source kind", maximum=16),
            "projection": _text(raw.get("projection"), label="training source projection", maximum=128),
            "stereo_layout": _text(raw.get("stereo_layout"), label="training source stereo layout", maximum=128),
            "width": _count(raw.get("width"), label="training source width"),
            "height": _count(raw.get("height"), label="training source height"),
            "information_score": _number(raw.get("information_score"), label="training source information score"),
        }
    return result


def _training_observations(value: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    raw_observations = value.get("training_observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise PhotorealTeacherBenchmarkPlanError("teacher input contains no training observations")
    by_source: dict[str, list[dict[str, Any]]] = {key: [] for key in sources}
    seen: set[tuple[str, str, float | None, str]] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherBenchmarkPlanError("teacher training observation is invalid")
        if _text(raw.get("split"), label="training observation split", maximum=32) != "train":
            raise PhotorealTeacherBenchmarkPlanError("teacher training observation is not train split")
        source_key = _text(raw.get("source_key"), label="training observation source key")
        if source_key not in sources:
            raise PhotorealTeacherBenchmarkPlanError("teacher observation references source outside training universe")
        frame_sha = _sha(raw.get("frame_sha256"), label="training observation frame SHA-256")
        timestamp = _timestamp(raw.get("timestamp_seconds"))
        eye = _text(raw.get("eye"), label="training observation eye", maximum=16)
        if eye not in {"mono", "left", "right"}:
            raise PhotorealTeacherBenchmarkPlanError("training observation eye is unsupported")
        key = (source_key, frame_sha, timestamp, eye)
        if key in seen:
            raise PhotorealTeacherBenchmarkPlanError("teacher input repeats training observation")
        seen.add(key)
        coverage_raw = raw.get("coverage")
        if not isinstance(coverage_raw, list):
            raise PhotorealTeacherBenchmarkPlanError("training observation coverage is invalid")
        coverage = sorted({_text(item, label="training observation coverage", maximum=64) for item in coverage_raw})
        by_source[source_key].append(
            {
                "source_key": source_key,
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": eye,
                "view_bin": _text(raw.get("view_bin"), label="training observation view bin", maximum=64),
                "coverage": coverage,
            }
        )
    for observations in by_source.values():
        observations.sort(
            key=lambda item: (
                -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
                item["eye"],
                item["frame_sha256"],
            )
        )
    return by_source


def _candidate(source: Mapping[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    if source["kind"] != "video" or source["projection"] != "flat" or source["stereo_layout"] != "mono":
        return None
    if not observations:
        return None
    if any(item["eye"] != "mono" or item["timestamp_seconds"] is None for item in observations):
        raise PhotorealTeacherBenchmarkPlanError("flat mono video candidate carries incompatible observations")
    coverage = sorted({label for item in observations for label in item["coverage"]})
    full_body_coverage = sorted(label for label in coverage if label.startswith("full-body-"))
    face_coverage = sorted(label for label in coverage if label.startswith("face-"))
    megapixels = (int(source["width"]) * int(source["height"])) / 1_000_000.0
    return {
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "resolved_path": source["resolved_path"],
        "group_id": source["group_id"],
        "projection": source["projection"],
        "stereo_layout": source["stereo_layout"],
        "width": source["width"],
        "height": source["height"],
        "megapixels": round(megapixels, 6),
        "information_score": round(float(source["information_score"]), 6),
        "observation_count": len(observations),
        "coverage": coverage,
        "coverage_count": len(coverage),
        "face_coverage_count": len(face_coverage),
        "full_body_coverage_count": len(full_body_coverage),
        "observations": observations,
    }


def _rank_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(candidate["coverage_count"]),
        -int(candidate["full_body_coverage_count"]),
        -int(candidate["face_coverage_count"]),
        -int(candidate["observation_count"]),
        -float(candidate["megapixels"]),
        -float(candidate["information_score"]),
        str(candidate["source_key"]),
    )


def build_teacher_benchmark_plan(teacher_input: Mapping[str, Any]) -> dict[str, Any]:
    performer_id, selected_epoch_id, teacher_input_sha256 = _validate_input(teacher_input)
    sources = _training_sources(teacher_input)
    observations = _training_observations(teacher_input, sources)

    candidates = [
        item
        for source_key, source in sources.items()
        if (item := _candidate(source, observations[source_key])) is not None
    ]
    candidates.sort(key=_rank_key)

    blockers: list[str] = []
    selected: dict[str, Any] | None = candidates[0] if candidates else None
    if selected is None:
        blockers.append("no authorized flat/mono training video exists in the selected appearance epoch")

    training_observation_count = _count(
        teacher_input.get("training_observation_count"), label="teacher training observation count"
    )
    training_source_count = _count(teacher_input.get("training_source_count"), label="teacher training source count")
    if training_source_count != len(sources):
        raise PhotorealTeacherBenchmarkPlanError("teacher input training source count mismatch")
    observed_count = sum(len(items) for items in observations.values())
    if training_observation_count != observed_count:
        raise PhotorealTeacherBenchmarkPlanError("teacher input training observation count mismatch")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": selected_epoch_id,
        "teacher_input_sha256": teacher_input_sha256,
        "benchmark": BENCHMARK,
        "strategy": STRATEGY,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": UPSTREAM_COMMIT,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_source_key": None if selected is None else selected["source_key"],
        "selected_source_sha256": None if selected is None else selected["source_sha256"],
        "selected_observation_count": 0 if selected is None else selected["observation_count"],
        "selected_observations": [] if selected is None else selected["observations"],
        "training_source_universe_count": training_source_count,
        "training_observation_universe_count": training_observation_count,
        "intended_source_utilization_fraction": 0.0 if selected is None else round(1 / training_source_count, 9),
        "intended_observation_utilization_fraction": (
            0.0 if selected is None or training_observation_count == 0 else round(selected["observation_count"] / training_observation_count, 9)
        ),
        "selection_authority": "core-benchmark-scheduling-only-v1",
        "benchmark_execution_authorized": selected is not None,
        "benchmark_blockers": blockers,
        "teacher_training_authority_inherited": teacher_input.get("teacher_training_authorized") is True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["benchmark_plan_sha256"] = _digest(result)
    return result


def build_teacher_benchmark_plan_files(
    teacher_input_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    teacher_input = _read_json(teacher_input_path, label="photoreal teacher input")
    result = build_teacher_benchmark_plan(teacher_input)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherBenchmarkPlanError(f"teacher benchmark plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
