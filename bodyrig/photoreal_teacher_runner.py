from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process

CONFIG_FORMAT = "bodyrig-photoreal-teacher-config"
CONFIG_VERSION = 1
INPUT_FORMAT = "bodyrig-photoreal-teacher-input"
INPUT_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-teacher-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-teacher-manifest"
RESULT_VERSION = 1

INPUT_FIELDS = {
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
INPUT_SOURCE_FIELDS = {
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
INPUT_OBSERVATION_FIELDS = {
    "source_key",
    "group_id",
    "split",
    "frame_sha256",
    "timestamp_seconds",
    "eye",
    "view_bin",
    "coverage",
}


class PhotorealTeacherRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherRunnerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherRunnerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return result


def _digest(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealTeacherRunnerError("teacher input canonical digest payload is invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


def _commit(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 40 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherRunnerError(f"{label} must be an exact 40-hex commit")
    return result


def _timestamp(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealTeacherRunnerError(f"{label} is invalid") from exc
    if not math.isfinite(result) or result < 0:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return round(result, 6)


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return value


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return value


def _nonnegative_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    return result


def _string_list(value: Any, *, label: str, minimum: int) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise PhotorealTeacherRunnerError(f"{label} is invalid")
    result = [_text(item, label=label, maximum=64) for item in value]
    if len(set(result)) != len(result):
        raise PhotorealTeacherRunnerError(f"{label} contains duplicates")
    return result


def _validate_input_source(raw: Any, *, label: str) -> tuple[str, str]:
    if not isinstance(raw, Mapping) or set(raw) != INPUT_SOURCE_FIELDS:
        raise PhotorealTeacherRunnerError(f"{label} fields must match v1 exactly")
    source_key = _text(raw.get("source_key"), label=f"{label} source key")
    group_id = _text(raw.get("group_id"), label=f"{label} group id")
    kind = _text(raw.get("kind"), label=f"{label} kind", maximum=16)
    if kind not in {"video", "image"}:
        raise PhotorealTeacherRunnerError(f"{label} kind is unsupported")
    _text(raw.get("resolved_path"), label=f"{label} resolved path", maximum=32768)
    _positive_int(raw.get("size_bytes"), label=f"{label} size_bytes")
    _sha(raw.get("sha256"), label=f"{label} SHA-256")
    _nonnegative_number(raw.get("information_score"), label=f"{label} information_score")
    _nonnegative_int(raw.get("width"), label=f"{label} width")
    _nonnegative_int(raw.get("height"), label=f"{label} height")
    _text(raw.get("projection"), label=f"{label} projection", maximum=128)
    _text(raw.get("stereo_layout"), label=f"{label} stereo layout", maximum=128)
    return source_key, group_id


def _validate_input_observation(raw: Any, *, label: str, expected_split: str) -> tuple[str, str, tuple[str, str, float | None, str]]:
    if not isinstance(raw, Mapping) or set(raw) != INPUT_OBSERVATION_FIELDS:
        raise PhotorealTeacherRunnerError(f"{label} fields must match v1 exactly")
    source_key = _text(raw.get("source_key"), label=f"{label} source key")
    group_id = _text(raw.get("group_id"), label=f"{label} group id")
    split = _text(raw.get("split"), label=f"{label} split", maximum=32)
    if split != expected_split:
        raise PhotorealTeacherRunnerError(f"{label} split must be {expected_split}")
    frame_sha = _sha(raw.get("frame_sha256"), label=f"{label} frame SHA-256")
    timestamp = _timestamp(raw.get("timestamp_seconds"), label=f"{label} timestamp")
    eye = _text(raw.get("eye"), label=f"{label} eye", maximum=16)
    if eye not in {"mono", "left", "right"}:
        raise PhotorealTeacherRunnerError(f"{label} eye is unsupported")
    _text(raw.get("view_bin"), label=f"{label} view bin", maximum=64)
    _string_list(raw.get("coverage"), label=f"{label} coverage", minimum=0)
    return source_key, group_id, (source_key, frame_sha, timestamp, eye)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_config(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "upstream_repository",
        "upstream_commit",
        "command",
        "timeout_seconds",
    }
    if set(value) != required:
        raise PhotorealTeacherRunnerError("teacher config fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != CONFIG_FORMAT or isinstance(version, bool) or version != CONFIG_VERSION:
        raise PhotorealTeacherRunnerError("teacher config format/version mismatch")
    adapter = _text(value.get("adapter"), label="teacher adapter", maximum=80)
    if any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealTeacherRunnerError("teacher adapter name is invalid")
    revision = _text(value.get("revision"), label="teacher adapter revision", maximum=160)
    repository = _text(value.get("upstream_repository"), label="teacher upstream repository", maximum=1024)
    if not repository.startswith("https://"):
        raise PhotorealTeacherRunnerError("teacher upstream repository must be an https URL")
    upstream_commit = _commit(value.get("upstream_commit"), label="teacher upstream commit")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealTeacherRunnerError("teacher command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 604800:
        raise PhotorealTeacherRunnerError("teacher timeout_seconds must be in 1..604800")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "upstream_repository": repository,
        "upstream_commit": upstream_commit,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def load_teacher_config(path: str | Path) -> dict[str, Any]:
    return _validate_config(_read_json(path, label="photoreal teacher config"))


def _validate_teacher_input(value: Mapping[str, Any]) -> None:
    if set(value) != INPUT_FIELDS:
        raise PhotorealTeacherRunnerError("teacher input fields must match v1 exactly")
    if value.get("format") != INPUT_FORMAT or value.get("version") != INPUT_VERSION:
        raise PhotorealTeacherRunnerError("teacher input format/version mismatch")
    digest_payload = dict(value)
    provided_digest = _sha(
        digest_payload.pop("teacher_input_sha256", None),
        label="teacher input SHA-256",
    )
    if _digest(digest_payload) != provided_digest:
        raise PhotorealTeacherRunnerError("teacher input digest mismatch")

    _text(value.get("performer_id"), label="teacher performer id", maximum=256)
    performer_name = value.get("performer_name")
    if not isinstance(performer_name, str) or len(performer_name) > 4096:
        raise PhotorealTeacherRunnerError("teacher performer name is invalid")
    _text(value.get("selected_epoch_id"), label="teacher epoch id", maximum=256)
    for key, label in (
        ("appearance_epoch_selection_sha256", "appearance epoch selection SHA-256"),
        ("identity_bank_sha256", "identity bank SHA-256"),
        ("identity_calibration_sha256", "identity calibration SHA-256"),
        ("analyzer_model_set_sha256", "analyzer model-set SHA-256"),
    ):
        _sha(value.get(key), label=label)

    if value.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherRunnerError("teacher input does not authorize training")
    if value.get("evaluation_bytes_excluded_from_teacher_request") is not True:
        raise PhotorealTeacherRunnerError("teacher input evaluation-leakage policy is invalid")
    required_coverage = set(
        _string_list(
            value.get("held_out_view_coverage_required"),
            label="teacher input held-out view coverage required",
            minimum=1,
        )
    )
    observed_coverage = set(
        _string_list(
            value.get("held_out_view_coverage_observed"),
            label="teacher input held-out view coverage observed",
            minimum=1,
        )
    )
    if value.get("held_out_view_coverage_missing") != [] or not required_coverage.issubset(observed_coverage):
        raise PhotorealTeacherRunnerError("teacher input held-out view coverage is incomplete")
    if value.get("photoreal_acceptance_authority") is not False or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherRunnerError("teacher input photoreal/human authority boundary is invalid")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealTeacherRunnerError("teacher input build/runtime authority boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealTeacherRunnerError("teacher input crossed production authority")

    train_sources = value.get("training_sources")
    held_out_sources = value.get("held_out_evaluation_sources")
    train_observations = value.get("training_observations")
    held_out_observations = value.get("held_out_evaluation_observations")
    if not isinstance(train_sources, list) or not train_sources:
        raise PhotorealTeacherRunnerError("teacher input has no training sources")
    if not isinstance(held_out_sources, list) or not held_out_sources:
        raise PhotorealTeacherRunnerError("teacher input has no held-out evaluation sources")
    if not isinstance(train_observations, list) or not train_observations:
        raise PhotorealTeacherRunnerError("teacher input has no training observations")
    if not isinstance(held_out_observations, list) or not held_out_observations:
        raise PhotorealTeacherRunnerError("teacher input has no held-out evaluation observations")

    train_source_groups: dict[str, str] = {}
    held_out_source_groups: dict[str, str] = {}
    for raw in train_sources:
        source_key, group_id = _validate_input_source(raw, label="teacher input training source")
        if source_key in train_source_groups:
            raise PhotorealTeacherRunnerError("teacher input repeats training source key")
        train_source_groups[source_key] = group_id
    for raw in held_out_sources:
        source_key, group_id = _validate_input_source(raw, label="teacher input held-out source")
        if source_key in held_out_source_groups:
            raise PhotorealTeacherRunnerError("teacher input repeats held-out source key")
        held_out_source_groups[source_key] = group_id
    if set(train_source_groups) & set(held_out_source_groups):
        raise PhotorealTeacherRunnerError("teacher input train/evaluation source universes overlap")

    train_observation_keys: set[tuple[str, str, float | None, str]] = set()
    held_out_observation_keys: set[tuple[str, str, float | None, str]] = set()
    train_observed_sources: set[str] = set()
    held_out_observed_sources: set[str] = set()
    for raw in train_observations:
        source_key, group_id, observation_key = _validate_input_observation(
            raw,
            label="teacher input training observation",
            expected_split="train",
        )
        if source_key not in train_source_groups or train_source_groups[source_key] != group_id:
            raise PhotorealTeacherRunnerError("teacher input training observation source/group binding mismatch")
        if observation_key in train_observation_keys:
            raise PhotorealTeacherRunnerError("teacher input repeats training observation")
        train_observation_keys.add(observation_key)
        train_observed_sources.add(source_key)
    for raw in held_out_observations:
        source_key, group_id, observation_key = _validate_input_observation(
            raw,
            label="teacher input held-out observation",
            expected_split="evaluation",
        )
        if source_key not in held_out_source_groups or held_out_source_groups[source_key] != group_id:
            raise PhotorealTeacherRunnerError("teacher input held-out observation source/group binding mismatch")
        if observation_key in held_out_observation_keys:
            raise PhotorealTeacherRunnerError("teacher input repeats held-out observation")
        held_out_observation_keys.add(observation_key)
        held_out_observed_sources.add(source_key)
    if train_observed_sources != set(train_source_groups):
        raise PhotorealTeacherRunnerError("teacher input training source lacks authorized observation")
    if held_out_observed_sources != set(held_out_source_groups):
        raise PhotorealTeacherRunnerError("teacher input held-out source lacks authorized observation")

    if _positive_int(value.get("training_source_count"), label="teacher input training source count") != len(train_sources):
        raise PhotorealTeacherRunnerError("teacher input training source count mismatch")
    if _positive_int(value.get("held_out_evaluation_source_count"), label="teacher input held-out source count") != len(held_out_sources):
        raise PhotorealTeacherRunnerError("teacher input held-out source count mismatch")
    if _positive_int(value.get("training_observation_count"), label="teacher input training observation count") != len(train_observations):
        raise PhotorealTeacherRunnerError("teacher input training observation count mismatch")
    if _positive_int(value.get("held_out_evaluation_observation_count"), label="teacher input held-out observation count") != len(held_out_observations):
        raise PhotorealTeacherRunnerError("teacher input held-out observation count mismatch")


def build_teacher_request(config: Mapping[str, Any], teacher_input: Mapping[str, Any]) -> dict[str, Any]:
    config = _validate_config(config)
    _validate_teacher_input(teacher_input)
    training_sources = teacher_input["training_sources"]
    training_observations = teacher_input["training_observations"]
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "performer_id": _text(teacher_input.get("performer_id"), label="teacher performer id", maximum=256),
        "selected_epoch_id": _text(teacher_input.get("selected_epoch_id"), label="teacher epoch id", maximum=256),
        "teacher_input_sha256": _sha(teacher_input.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "adapter": config["adapter"],
        "adapter_revision": config["revision"],
        "upstream_repository": config["upstream_repository"],
        "upstream_commit": config["upstream_commit"],
        "training_sources": training_sources,
        "training_observations": training_observations,
        "held_out_evaluation_source_count": int(teacher_input.get("held_out_evaluation_source_count") or 0),
        "held_out_evaluation_observation_count": int(teacher_input.get("held_out_evaluation_observation_count") or 0),
        "held_out_paths_disclosed": False,
        "held_out_frame_hashes_disclosed": False,
        "train_evaluation_authority": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }


def _safe_artifact_path(output_dir: Path, relative: Any) -> Path:
    value = _text(relative, label="teacher artifact relative path", maximum=4096).replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealTeacherRunnerError("teacher artifact path escapes output workspace")
    target = (output_dir / Path(value)).resolve()
    try:
        target.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise PhotorealTeacherRunnerError("teacher artifact path escapes output workspace") from exc
    return target


def _training_source_universe(request: Mapping[str, Any]) -> set[str]:
    values = request.get("training_sources")
    if not isinstance(values, list) or not values:
        raise PhotorealTeacherRunnerError("teacher request has no training source universe")
    result: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherRunnerError("teacher request training source is invalid")
        source_key = _text(raw.get("source_key"), label="teacher request training source key")
        if source_key in result:
            raise PhotorealTeacherRunnerError("teacher request repeats training source key")
        result.add(source_key)
    return result


def _observation_key(raw: Mapping[str, Any], *, label: str) -> tuple[str, str, float | None, str]:
    source_key = _text(raw.get("source_key"), label=f"{label} source key")
    frame_sha = _sha(raw.get("frame_sha256"), label=f"{label} frame SHA-256")
    timestamp = _timestamp(raw.get("timestamp_seconds"), label=f"{label} timestamp")
    eye = _text(raw.get("eye"), label=f"{label} eye", maximum=16)
    if eye not in {"mono", "left", "right"}:
        raise PhotorealTeacherRunnerError(f"{label} eye is unsupported")
    return source_key, frame_sha, timestamp, eye


def _training_observation_universe(request: Mapping[str, Any]) -> set[tuple[str, str, float | None, str]]:
    values = request.get("training_observations")
    if not isinstance(values, list) or not values:
        raise PhotorealTeacherRunnerError("teacher request has no training observation universe")
    result: set[tuple[str, str, float | None, str]] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherRunnerError("teacher request training observation is invalid")
        key = _observation_key(raw, label="teacher request training observation")
        if key in result:
            raise PhotorealTeacherRunnerError("teacher request repeats training observation")
        result.add(key)
    return result


def _validate_consumed_training(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    source_universe = _training_source_universe(request)
    observation_universe = _training_observation_universe(request)

    consumed_sources_raw = value.get("consumed_training_source_keys")
    if not isinstance(consumed_sources_raw, list) or not consumed_sources_raw:
        raise PhotorealTeacherRunnerError("teacher manifest contains no consumed training sources")
    consumed_sources: list[str] = []
    seen_sources: set[str] = set()
    for raw in consumed_sources_raw:
        source_key = _text(raw, label="consumed training source key")
        if source_key in seen_sources:
            raise PhotorealTeacherRunnerError("teacher manifest repeats consumed training source")
        if source_key not in source_universe:
            raise PhotorealTeacherRunnerError("teacher manifest consumed source outside authorized training universe")
        seen_sources.add(source_key)
        consumed_sources.append(source_key)

    consumed_observations_raw = value.get("consumed_training_observations")
    if not isinstance(consumed_observations_raw, list) or not consumed_observations_raw:
        raise PhotorealTeacherRunnerError("teacher manifest contains no consumed training observations")
    consumed_observations: list[dict[str, Any]] = []
    seen_observations: set[tuple[str, str, float | None, str]] = set()
    observation_sources: set[str] = set()
    required_fields = {"source_key", "frame_sha256", "timestamp_seconds", "eye"}
    for raw in consumed_observations_raw:
        if not isinstance(raw, Mapping) or set(raw) != required_fields:
            raise PhotorealTeacherRunnerError("consumed training observation fields must match v1 exactly")
        key = _observation_key(raw, label="consumed training observation")
        if key in seen_observations:
            raise PhotorealTeacherRunnerError("teacher manifest repeats consumed training observation")
        if key not in observation_universe:
            raise PhotorealTeacherRunnerError("teacher manifest consumed observation outside authorized training universe")
        if key[0] not in seen_sources:
            raise PhotorealTeacherRunnerError("teacher manifest consumed observation from undeclared training source")
        seen_observations.add(key)
        observation_sources.add(key[0])
        consumed_observations.append(
            {
                "source_key": key[0],
                "frame_sha256": key[1],
                "timestamp_seconds": key[2],
                "eye": key[3],
            }
        )
    if observation_sources != seen_sources:
        raise PhotorealTeacherRunnerError("each consumed training source must have at least one consumed observation")

    consumed_sources.sort()
    consumed_observations.sort(
        key=lambda item: (
            item["source_key"],
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            item["eye"],
            item["frame_sha256"],
        )
    )
    utilization = {
        "training_source_universe_count": len(source_universe),
        "consumed_training_source_count": len(consumed_sources),
        "training_source_utilization_fraction": round(len(consumed_sources) / len(source_universe), 9),
        "training_observation_universe_count": len(observation_universe),
        "consumed_training_observation_count": len(consumed_observations),
        "training_observation_utilization_fraction": round(len(consumed_observations) / len(observation_universe), 9),
    }
    return consumed_sources, consumed_observations, utilization


def validate_teacher_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "adapter",
        "adapter_revision",
        "upstream_repository",
        "upstream_commit",
        "training_complete",
        "consumed_training_source_keys",
        "consumed_training_observations",
        "artifacts",
        "photoreal_acceptance_authority",
        "human_visual_acceptance_required",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealTeacherRunnerError("teacher manifest fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != RESULT_FORMAT or isinstance(version, bool) or version != RESULT_VERSION:
        raise PhotorealTeacherRunnerError("teacher manifest format/version mismatch")
    for key in ("performer_id", "selected_epoch_id", "adapter", "adapter_revision", "upstream_repository", "upstream_commit"):
        if str(value.get(key) or "") != str(request.get(key) or ""):
            raise PhotorealTeacherRunnerError(f"teacher manifest provenance mismatch: {key}")
    if _sha(value.get("teacher_input_sha256"), label="teacher manifest input SHA-256") != request["teacher_input_sha256"]:
        raise PhotorealTeacherRunnerError("teacher manifest targets different input")
    if value.get("training_complete") is not True:
        raise PhotorealTeacherRunnerError("teacher adapter did not report complete training")
    if value.get("photoreal_acceptance_authority") is not False or value.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherRunnerError("teacher manifest crossed photoreal/human authority")
    if value.get("production_activation") is not False:
        raise PhotorealTeacherRunnerError("teacher manifest crossed production authority")

    consumed_sources, consumed_observations, utilization = _validate_consumed_training(value, request=request)

    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealTeacherRunnerError("teacher manifest contains no artifacts")
    seen: set[str] = set()
    listed_files: set[str] = set()
    normalized_artifacts: list[dict[str, Any]] = []
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "relative_path", "size_bytes", "sha256"}:
            raise PhotorealTeacherRunnerError("teacher artifact entry fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="teacher artifact kind", maximum=64)
        relative = _text(raw.get("relative_path"), label="teacher artifact relative path", maximum=4096).replace("\\", "/")
        if relative == "teacher-manifest.json" or relative in seen:
            raise PhotorealTeacherRunnerError("teacher artifact list repeats/reserves output path")
        seen.add(relative)
        path = _safe_artifact_path(output_dir, relative)
        if not path.is_file():
            raise PhotorealTeacherRunnerError(f"teacher artifact is missing: {relative}")
        observed_size = path.stat().st_size
        declared_size = raw.get("size_bytes")
        if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size != observed_size or observed_size < 1:
            raise PhotorealTeacherRunnerError(f"teacher artifact size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if _sha(raw.get("sha256"), label="teacher artifact SHA-256") != observed_sha:
            raise PhotorealTeacherRunnerError(f"teacher artifact SHA-256 mismatch: {relative}")
        listed_files.add(relative)
        normalized_artifacts.append(
            {"kind": kind, "relative_path": relative, "size_bytes": observed_size, "sha256": observed_sha}
        )

    actual_files = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "teacher-manifest.json"
    }
    if actual_files != listed_files:
        extra = sorted(actual_files - listed_files)
        missing = sorted(listed_files - actual_files)
        raise PhotorealTeacherRunnerError(
            f"teacher output artifact universe mismatch (extra={len(extra)}, missing={len(missing)})"
        )
    result = dict(value)
    result["consumed_training_source_keys"] = consumed_sources
    result["consumed_training_observations"] = consumed_observations
    result["artifacts"] = sorted(normalized_artifacts, key=lambda item: item["relative_path"])
    result.update(utilization)
    return result


def _log_tail(path: Path, limit: int = 8000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def _invoke_teacher_adapter(
    config: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    request_path: Path,
    output_dir: Path,
    log_path: Path,
) -> dict[str, Any]:
    invoke = [
        *list(config["command"]),
        "--bodyrig-request",
        str(request_path),
        "--bodyrig-output",
        str(output_dir),
        "--bodyrig-adapter",
        config["adapter"],
        "--bodyrig-revision",
        config["revision"],
        "--bodyrig-upstream-commit",
        config["upstream_commit"],
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealTeacherRunnerError(
            f"teacher adapter timed out after {config['timeout_seconds']} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealTeacherRunnerError(f"teacher adapter process could not complete: {exc}{suffix}") from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealTeacherRunnerError(
            f"teacher adapter failed with exit code {completed.returncode}{suffix}"
        )
    manifest_path = output_dir / "teacher-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealTeacherRunnerError("teacher adapter did not create teacher-manifest.json")
    manifest = _read_json(manifest_path, label="teacher manifest")
    return validate_teacher_result(manifest, request=request, output_dir=output_dir)


def _next_resume_log(root: Path) -> Path:
    for index in range(1, 1000):
        candidate = root / f"adapter-resume-{index:03d}.log"
        if not candidate.exists():
            return candidate
    raise PhotorealTeacherRunnerError("teacher workspace exhausted resume log slots")


def run_external_teacher(
    config: Mapping[str, Any],
    teacher_input: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    config = _validate_config(config)
    request = build_teacher_request(config, teacher_input)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealTeacherRunnerError(f"teacher workspace already exists: {root}")
    root.mkdir(parents=True)
    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return _invoke_teacher_adapter(
        config,
        request,
        request_path=request_path,
        output_dir=output_dir,
        log_path=log_path,
    )


def resume_external_teacher(
    config: Mapping[str, Any],
    teacher_input: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    config = _validate_config(config)
    request = build_teacher_request(config, teacher_input)
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealTeacherRunnerError(f"teacher resume workspace is missing: {root}")
    request_path = root / "request.json"
    output_dir = root / "output"
    if not request_path.is_file():
        raise PhotorealTeacherRunnerError("teacher resume workspace has no request.json")
    if not output_dir.is_dir():
        raise PhotorealTeacherRunnerError("teacher resume workspace has no output directory")
    existing_request = _read_json(request_path, label="existing teacher request")
    if existing_request != request:
        raise PhotorealTeacherRunnerError("teacher resume request differs from existing workspace request")
    if (output_dir / "teacher-manifest.json").exists():
        raise PhotorealTeacherRunnerError(
            "teacher resume workspace is already complete; use strict reuse validation"
        )
    if any(output_dir.iterdir()):
        raise PhotorealTeacherRunnerError(
            "teacher incomplete output directory is not empty; refusing ambiguous resume"
        )
    return _invoke_teacher_adapter(
        config,
        request,
        request_path=request_path,
        output_dir=output_dir,
        log_path=_next_resume_log(root),
    )

def run_external_teacher_files(
    config_path: str | Path,
    teacher_input_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_teacher_config(config_path)
    teacher_input = _read_json(teacher_input_path, label="photoreal teacher input")
    return run_external_teacher(config, teacher_input, workspace=workspace)


def resume_external_teacher_files(
    config_path: str | Path,
    teacher_input_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_teacher_config(config_path)
    teacher_input = _read_json(teacher_input_path, label="photoreal teacher input")
    return resume_external_teacher(config, teacher_input, workspace=workspace)
