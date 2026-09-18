from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, TypeAlias

from .photoreal_teacher_input import (
    FORMAT as TEACHER_INPUT_FORMAT,
    FRAME_INDEX_FORMAT,
    FRAME_INDEX_VERSION,
    PLAN_FORMAT,
    PLAN_VERSION,
    RECEIPT_FORMAT,
    RECEIPT_VERSION,
    SELECTION_FORMAT,
    SELECTION_VERSION,
    VERSION as TEACHER_INPUT_VERSION,
    PhotorealTeacherInputError,
    build_teacher_input,
)
from .photoreal_teacher_runner import (
    PhotorealTeacherRunnerError,
    build_teacher_request,
    load_teacher_config,
    run_external_teacher,
    validate_teacher_result,
)

ErrorType: TypeAlias = type[ValueError]

_TEACHER_INPUT_FIELDS = {
    "format",
    "version",
    "performer_id",
    "performer_name",
    "selected_epoch_id",
    "appearance_epoch_selection_sha256",
    "identity_bank_sha256",
    "identity_calibration_sha256",
    "analyzer_model_set_sha256",
    "training_sources",
    "held_out_evaluation_sources",
    "training_observations",
    "held_out_evaluation_observations",
    "held_out_view_coverage_required",
    "held_out_view_coverage_observed",
    "held_out_view_coverage_missing",
    "training_source_count",
    "held_out_evaluation_source_count",
    "training_observation_count",
    "held_out_evaluation_observation_count",
    "evaluation_bytes_excluded_from_teacher_request",
    "teacher_training_authorized",
    "photoreal_acceptance_authority",
    "human_visual_acceptance_required",
    "build_only",
    "runtime_dependency",
    "production_activation",
    "teacher_input_sha256",
}
_SOURCE_FIELDS = {
    "source_key",
    "group_id",
    "kind",
    "resolved_path",
    "size_bytes",
    "sha256",
    "information_score",
    "width",
    "height",
    "projection",
    "stereo_layout",
}
_OBSERVATION_FIELDS = {
    "source_key",
    "group_id",
    "split",
    "frame_sha256",
    "timestamp_seconds",
    "eye",
    "view_bin",
    "coverage",
}


def _read_json(path: str | Path, *, label: str, error_type: ErrorType) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise error_type(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise error_type(f"{label} must be a JSON object")
    return value


def _numeric_v1(value: Any, *, label: str, error_type: ErrorType) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise error_type(f"{label} version must be numeric v1")


def _format_v1(
    value: Mapping[str, Any],
    *,
    expected_format: str,
    expected_version: int,
    label: str,
    error_type: ErrorType,
) -> None:
    if value.get("format") != expected_format:
        raise error_type(f"{label} format/version mismatch")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, float)):
        raise error_type(f"{label} format/version mismatch")
    if not math.isfinite(float(version)) or version != expected_version:
        raise error_type(f"{label} format/version mismatch")


def _text(value: Any, *, label: str, error_type: ErrorType, maximum: int = 4096, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise error_type(f"{label} is invalid")
    result = value.strip()
    if (not result and not allow_empty) or len(value) > maximum:
        raise error_type(f"{label} is invalid")
    return value


def _sha(value: Any, *, label: str, error_type: ErrorType) -> str:
    if not isinstance(value, str):
        raise error_type(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise error_type(f"{label} is invalid")
    return result


def _positive_int(value: Any, *, label: str, error_type: ErrorType) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise error_type(f"{label} is invalid")
    return value


def _non_negative_int(value: Any, *, label: str, error_type: ErrorType) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise error_type(f"{label} is invalid")
    return value


def _non_negative_number(value: Any, *, label: str, error_type: ErrorType) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise error_type(f"{label} is invalid")
    return result


def _timestamp(value: Any, *, label: str, error_type: ErrorType) -> None:
    if value is None:
        return
    _non_negative_number(value, label=label, error_type=error_type)


def _string_set(
    value: Any,
    *,
    label: str,
    error_type: ErrorType,
    require_nonempty: bool,
    maximum: int = 64,
) -> set[str]:
    if not isinstance(value, list) or (require_nonempty and not value):
        raise error_type(f"{label} is invalid")
    result: set[str] = set()
    for raw in value:
        item = _text(raw, label=label, error_type=error_type, maximum=maximum)
        if item in result:
            raise error_type(f"{label} contains duplicates")
        result.add(item)
    return result


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_teacher_input_upstream_versions(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    epoch_selection: Mapping[str, Any],
) -> None:
    _format_v1(
        plan,
        expected_format=PLAN_FORMAT,
        expected_version=PLAN_VERSION,
        label="dataset plan",
        error_type=PhotorealTeacherInputError,
    )
    _format_v1(
        receipt,
        expected_format=RECEIPT_FORMAT,
        expected_version=RECEIPT_VERSION,
        label="source receipt",
        error_type=PhotorealTeacherInputError,
    )
    _format_v1(
        frame_index,
        expected_format=FRAME_INDEX_FORMAT,
        expected_version=FRAME_INDEX_VERSION,
        label="frame index",
        error_type=PhotorealTeacherInputError,
    )
    _format_v1(
        epoch_selection,
        expected_format=SELECTION_FORMAT,
        expected_version=SELECTION_VERSION,
        label="appearance epoch selection",
        error_type=PhotorealTeacherInputError,
    )


def _validate_sources(
    values: Any,
    *,
    label: str,
    error_type: ErrorType,
) -> tuple[dict[str, str], set[str]]:
    if not isinstance(values, list) or not values:
        raise error_type(f"{label} is invalid")
    source_groups: dict[str, str] = {}
    groups: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != _SOURCE_FIELDS:
            raise error_type(f"{label} fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label=f"{label} source_key", error_type=error_type)
        if source_key in source_groups:
            raise error_type(f"{label} repeats source_key")
        group_id = _text(raw.get("group_id"), label=f"{label} group_id", error_type=error_type)
        kind = raw.get("kind")
        if kind not in {"video", "image"}:
            raise error_type(f"{label} kind is invalid")
        _text(raw.get("resolved_path"), label=f"{label} resolved_path", error_type=error_type, maximum=32768)
        _positive_int(raw.get("size_bytes"), label=f"{label} size_bytes", error_type=error_type)
        _sha(raw.get("sha256"), label=f"{label} sha256", error_type=error_type)
        _non_negative_number(raw.get("information_score"), label=f"{label} information_score", error_type=error_type)
        _non_negative_int(raw.get("width"), label=f"{label} width", error_type=error_type)
        _non_negative_int(raw.get("height"), label=f"{label} height", error_type=error_type)
        _text(raw.get("projection"), label=f"{label} projection", error_type=error_type, maximum=128)
        _text(raw.get("stereo_layout"), label=f"{label} stereo_layout", error_type=error_type, maximum=128)
        source_groups[source_key] = group_id
        groups.add(group_id)
    return source_groups, groups


def _validate_observations(
    values: Any,
    *,
    label: str,
    expected_split: str,
    source_groups: Mapping[str, str],
    error_type: ErrorType,
) -> set[str]:
    if not isinstance(values, list) or not values:
        raise error_type(f"{label} is invalid")
    observed_sources: set[str] = set()
    seen: set[tuple[str, str, float | None, str]] = set()
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != _OBSERVATION_FIELDS:
            raise error_type(f"{label} fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label=f"{label} source_key", error_type=error_type)
        if source_key not in source_groups:
            raise error_type(f"{label} references source outside its split")
        group_id = _text(raw.get("group_id"), label=f"{label} group_id", error_type=error_type)
        if group_id != source_groups[source_key]:
            raise error_type(f"{label} group/source binding mismatch")
        if raw.get("split") != expected_split:
            raise error_type(f"{label} split is invalid")
        frame_sha = _sha(raw.get("frame_sha256"), label=f"{label} frame_sha256", error_type=error_type)
        timestamp = raw.get("timestamp_seconds")
        _timestamp(timestamp, label=f"{label} timestamp_seconds", error_type=error_type)
        eye = raw.get("eye")
        if eye not in {"mono", "left", "right"}:
            raise error_type(f"{label} eye is invalid")
        _text(raw.get("view_bin"), label=f"{label} view_bin", error_type=error_type, maximum=64)
        _string_set(raw.get("coverage"), label=f"{label} coverage", error_type=error_type, require_nonempty=False)
        timestamp_key = None if timestamp is None else round(float(timestamp), 6)
        key = (source_key, frame_sha, timestamp_key, str(eye))
        if key in seen:
            raise error_type(f"{label} repeats observation")
        seen.add(key)
        observed_sources.add(source_key)
    if observed_sources != set(source_groups):
        raise error_type(f"{label} source universe is not fully represented")
    return observed_sources


def validate_teacher_input_document(value: Mapping[str, Any]) -> dict[str, Any]:
    error_type = PhotorealTeacherRunnerError
    if set(value) != _TEACHER_INPUT_FIELDS:
        raise error_type("teacher input fields must match v1 exactly")
    _format_v1(
        value,
        expected_format=TEACHER_INPUT_FORMAT,
        expected_version=TEACHER_INPUT_VERSION,
        label="teacher input",
        error_type=error_type,
    )
    _text(value.get("performer_id"), label="teacher performer_id", error_type=error_type, maximum=256)
    _text(
        value.get("performer_name"),
        label="teacher performer_name",
        error_type=error_type,
        maximum=4096,
        allow_empty=True,
    )
    _text(value.get("selected_epoch_id"), label="teacher selected_epoch_id", error_type=error_type, maximum=256)
    for key in (
        "appearance_epoch_selection_sha256",
        "identity_bank_sha256",
        "identity_calibration_sha256",
        "analyzer_model_set_sha256",
    ):
        _sha(value.get(key), label=f"teacher {key}", error_type=error_type)

    train_sources, train_groups = _validate_sources(
        value.get("training_sources"), label="teacher training_sources", error_type=error_type
    )
    eval_sources, eval_groups = _validate_sources(
        value.get("held_out_evaluation_sources"), label="teacher held_out_evaluation_sources", error_type=error_type
    )
    if set(train_sources) & set(eval_sources):
        raise error_type("teacher input train/evaluation source keys overlap")
    if train_groups & eval_groups:
        raise error_type("teacher input train/evaluation source groups overlap")

    _validate_observations(
        value.get("training_observations"),
        label="teacher training_observations",
        expected_split="train",
        source_groups=train_sources,
        error_type=error_type,
    )
    _validate_observations(
        value.get("held_out_evaluation_observations"),
        label="teacher held_out_evaluation_observations",
        expected_split="evaluation",
        source_groups=eval_sources,
        error_type=error_type,
    )

    required = _string_set(
        value.get("held_out_view_coverage_required"),
        label="teacher held_out_view_coverage_required",
        error_type=error_type,
        require_nonempty=True,
    )
    observed = _string_set(
        value.get("held_out_view_coverage_observed"),
        label="teacher held_out_view_coverage_observed",
        error_type=error_type,
        require_nonempty=True,
    )
    if value.get("held_out_view_coverage_missing") != [] or not required.issubset(observed):
        raise error_type("teacher input held-out view coverage is incomplete")

    count_bindings = (
        ("training_source_count", len(train_sources)),
        ("held_out_evaluation_source_count", len(eval_sources)),
        ("training_observation_count", len(value["training_observations"])),
        ("held_out_evaluation_observation_count", len(value["held_out_evaluation_observations"])),
    )
    for key, expected in count_bindings:
        actual = _positive_int(value.get(key), label=f"teacher {key}", error_type=error_type)
        if actual != expected:
            raise error_type(f"teacher input count mismatch: {key}")

    if value.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise error_type("teacher input evaluation-leakage policy is invalid")
    if value.get("teacher_training_authorized") is not True:
        raise error_type("teacher input does not authorize training")
    if value.get("photoreal_acceptance_authority") is not False:
        raise error_type("teacher input crossed photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise error_type("teacher input removed human visual acceptance")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise error_type("teacher input build/runtime authority boundary is invalid")
    if value.get("production_activation") is not False:
        raise error_type("teacher input crossed production authority")

    declared = _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256", error_type=error_type)
    unhashed = dict(value)
    unhashed.pop("teacher_input_sha256", None)
    try:
        observed_digest = _canonical_digest(unhashed)
    except (TypeError, ValueError) as exc:
        raise error_type("teacher input cannot be canonically hashed") from exc
    if declared != observed_digest:
        raise error_type("teacher input SHA-256 does not match manifest content")
    return dict(value)


def build_teacher_input_files_strict(
    plan_path: str | Path,
    receipt_path: str | Path,
    frame_index_path: str | Path,
    epoch_selection_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan", error_type=PhotorealTeacherInputError)
    receipt = _read_json(receipt_path, label="photoreal source receipt", error_type=PhotorealTeacherInputError)
    frame_index = _read_json(frame_index_path, label="photoreal frame index", error_type=PhotorealTeacherInputError)
    selection = _read_json(
        epoch_selection_path,
        label="appearance epoch selection",
        error_type=PhotorealTeacherInputError,
    )
    validate_teacher_input_upstream_versions(plan, receipt, frame_index, selection)
    result = build_teacher_input(plan, receipt, frame_index, selection)
    validate_teacher_input_document(result)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherInputError(f"teacher input manifest already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def validate_external_teacher_files_strict(
    config_path: str | Path,
    teacher_input_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_teacher_config(config_path)
    teacher_input = _read_json(
        teacher_input_path,
        label="photoreal teacher input",
        error_type=PhotorealTeacherRunnerError,
    )
    validated = validate_teacher_input_document(teacher_input)
    request = build_teacher_request(config, validated)
    output = Path(workspace).expanduser().resolve()
    if not output.is_dir():
        raise PhotorealTeacherRunnerError(f"teacher output workspace is missing: {output}")
    manifest = _read_json(
        output / "teacher-manifest.json",
        label="photoreal teacher manifest",
        error_type=PhotorealTeacherRunnerError,
    )
    return validate_teacher_result(manifest, request=request, output_dir=output)


def run_external_teacher_files_strict(
    config_path: str | Path,
    teacher_input_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_teacher_config(config_path)
    teacher_input = _read_json(
        teacher_input_path,
        label="photoreal teacher input",
        error_type=PhotorealTeacherRunnerError,
    )
    validated = validate_teacher_input_document(teacher_input)
    return run_external_teacher(config, validated, workspace=workspace)
