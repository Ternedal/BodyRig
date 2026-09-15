from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .logged_process import LoggedProcessError, run_logged_process
from .photoreal_device_distillation_authority import (
    PhotorealDeviceDistillationAuthorityError,
    require_distillation_execution_authority,
)
from .photoreal_device_distillation_plan import (
    CANDIDATE_REPRESENTATIONS,
    FIDELITY_DIMENSIONS,
    TARGET_MODELS,
)

CONFIG_FORMAT = "bodyrig-photoreal-device-distillation-config"
CONFIG_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-device-distillation-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-device-distillation-manifest"
RESULT_VERSION = 1
MAX_TIMEOUT_SECONDS = 604800

CONFIG_FIELDS = {
    "format",
    "version",
    "adapter",
    "revision",
    "student_representation",
    "command",
    "timeout_seconds",
    "supported_target_models",
    "supported_fidelity_delta_dimensions",
    "reports_teacher_student_delta",
    "gaussian_splat_target_support",
}
RESULT_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "teacher_manifest_sha256",
    "static_teacher_review_sha256",
    "animation_plan_sha256",
    "animation_execution_receipt_sha256",
    "animated_teacher_review_sha256",
    "device_distillation_plan_sha256",
    "target_profile_sha256",
    "adapter",
    "adapter_revision",
    "student_representation",
    "distillation_complete",
    "consumed_distillation_source_artifacts",
    "fidelity_delta_measurements",
    "student_artifacts",
    "student_fidelity_claim_exceeds_teacher",
    "human_runtime_visual_acceptance_required",
    "runtime_acceptance_authority",
    "production_activation",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}
CONSUMED_FIELDS = {"relative_path", "sha256"}
MEASUREMENT_FIELDS = {"dimension", "metric", "value", "unit", "teacher_reference", "student_reference"}


class PhotorealDeviceDistillationRunnerError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceDistillationRunnerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceDistillationRunnerError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationRunnerError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealDeviceDistillationRunnerError(f"{label} version must be numeric v1")


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealDeviceDistillationRunnerError(f"{label} is invalid")
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceDistillationRunnerError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealDeviceDistillationRunnerError(f"{label} escapes its root") from exc
    return clean, target


def validate_distillation_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != CONFIG_FIELDS or value.get("format") != CONFIG_FORMAT:
        raise PhotorealDeviceDistillationRunnerError("distillation config fields/format mismatch")
    _v1(value.get("version"), label="distillation config")
    adapter = _text(value.get("adapter"), label="distillation adapter", maximum=80)
    if any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealDeviceDistillationRunnerError("distillation adapter name is invalid")
    revision = _text(value.get("revision"), label="distillation adapter revision", maximum=160)
    representation = value.get("student_representation")
    if representation not in CANDIDATE_REPRESENTATIONS:
        raise PhotorealDeviceDistillationRunnerError("distillation student representation is not canonical")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealDeviceDistillationRunnerError("distillation command must be a non-empty argv list")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PhotorealDeviceDistillationRunnerError("distillation timeout_seconds is invalid")
    supported = value.get("supported_target_models")
    if not isinstance(supported, list) or not supported:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter has no supported target models")
    normalized_models: list[str] = []
    seen_models: set[str] = set()
    for model in supported:
        if model not in TARGET_MODELS or model in seen_models:
            raise PhotorealDeviceDistillationRunnerError("distillation supported target models are invalid")
        seen_models.add(str(model))
        normalized_models.append(str(model))
    normalized_models.sort()
    if supported != normalized_models:
        raise PhotorealDeviceDistillationRunnerError("distillation supported target models must be canonical sorted unique values")
    if value.get("supported_fidelity_delta_dimensions") != list(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationRunnerError("distillation adapter does not report the canonical fidelity delta universe")
    if value.get("reports_teacher_student_delta") is not True:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter does not report teacher-to-student deltas")
    gaussian_support = value.get("gaussian_splat_target_support")
    if not isinstance(gaussian_support, bool):
        raise PhotorealDeviceDistillationRunnerError("gaussian_splat_target_support must be boolean")
    if representation == "gaussian-splat-optional" and gaussian_support is not True:
        raise PhotorealDeviceDistillationRunnerError("Gaussian/splat representation requires explicit target support")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "student_representation": str(representation),
        "command": list(command),
        "timeout_seconds": timeout,
        "supported_target_models": normalized_models,
        "supported_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "reports_teacher_student_delta": True,
        "gaussian_splat_target_support": gaussian_support,
    }


def load_distillation_config(path: str | Path) -> dict[str, Any]:
    return validate_distillation_config(_read_json(path, label="device distillation config"))


def _validate_source_root(plan: Mapping[str, Any], root: Path) -> None:
    if not root.is_dir():
        raise PhotorealDeviceDistillationRunnerError(f"distillation source root not found: {root}")
    expected: set[str] = set()
    for raw in plan["distillation_source_artifacts"]:
        relative, path = _safe_child(root, raw.get("relative_path"), label="distillation source artifact path")
        if relative in expected:
            raise PhotorealDeviceDistillationRunnerError("distillation plan repeats source artifact")
        expected.add(relative)
        if not path.is_file():
            raise PhotorealDeviceDistillationRunnerError(f"distillation source artifact is missing: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
            raise PhotorealDeviceDistillationRunnerError(f"distillation source artifact size drifted: {relative}")
        if _hash_file(path) != _sha(raw.get("sha256"), label="distillation source artifact SHA-256"):
            raise PhotorealDeviceDistillationRunnerError(f"distillation source artifact bytes drifted: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "animation-manifest.json"
    }
    if actual != expected:
        raise PhotorealDeviceDistillationRunnerError("distillation source artifact universe drifted before execution")


def build_distillation_request(
    config: Mapping[str, Any],
    distillation_plan: Mapping[str, Any],
    *,
    animation_output_root: str | Path,
) -> dict[str, Any]:
    config = validate_distillation_config(config)
    try:
        plan = require_distillation_execution_authority(distillation_plan)
    except PhotorealDeviceDistillationAuthorityError as exc:
        raise PhotorealDeviceDistillationRunnerError(str(exc)) from exc
    target_model = plan["target_profile"]["target_model"]
    if target_model not in config["supported_target_models"]:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter does not support the planned target model")
    if config["student_representation"] not in plan["candidate_student_representations"]:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter selected representation outside plan authority")
    if config["student_representation"] == "gaussian-splat-optional" and config["gaussian_splat_target_support"] is not True:
        raise PhotorealDeviceDistillationRunnerError("Gaussian/splat representation lacks explicit target support")
    source_root = Path(animation_output_root).expanduser().resolve()
    _validate_source_root(plan, source_root)
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "teacher_manifest_sha256": plan["teacher_manifest_sha256"],
        "static_teacher_review_sha256": plan["static_teacher_review_sha256"],
        "animation_plan_sha256": plan["animation_plan_sha256"],
        "animation_execution_receipt_sha256": plan["animation_execution_receipt_sha256"],
        "animated_teacher_review_sha256": plan["animated_teacher_review_sha256"],
        "device_distillation_plan_sha256": plan["device_distillation_plan_sha256"],
        "target_profile": plan["target_profile"],
        "target_profile_sha256": plan["target_profile_sha256"],
        "adapter": config["adapter"],
        "adapter_revision": config["revision"],
        "student_representation": config["student_representation"],
        "distillation_source_artifacts": plan["distillation_source_artifacts"],
        "required_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "p3_distillation_execution_authorized": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }


def _source_universe(request: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in request["distillation_source_artifacts"]:
        relative = _relative_path(raw.get("relative_path"), label="request distillation source artifact path")
        if relative in result:
            raise PhotorealDeviceDistillationRunnerError("distillation request repeats source artifact")
        result[relative] = _sha(raw.get("sha256"), label="request distillation source artifact SHA-256")
    return result


def validate_distillation_result(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if set(value) != RESULT_FIELDS or value.get("format") != RESULT_FORMAT:
        raise PhotorealDeviceDistillationRunnerError("distillation manifest fields/format mismatch")
    _v1(value.get("version"), label="distillation manifest")
    for key in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
        "animation_execution_receipt_sha256",
        "animated_teacher_review_sha256",
        "device_distillation_plan_sha256",
        "target_profile_sha256",
        "adapter",
        "adapter_revision",
        "student_representation",
    ):
        if value.get(key) != request.get(key):
            raise PhotorealDeviceDistillationRunnerError(f"distillation manifest provenance mismatch: {key}")
    if value.get("distillation_complete") is not True:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter did not report complete execution")
    if value.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter claimed student fidelity above teacher")
    if value.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter removed human runtime acceptance")
    if value.get("runtime_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealDeviceDistillationRunnerError("distillation adapter crossed runtime/production authority")

    source_universe = _source_universe(request)
    consumed = value.get("consumed_distillation_source_artifacts")
    if not isinstance(consumed, list) or len(consumed) != len(source_universe):
        raise PhotorealDeviceDistillationRunnerError("distillation manifest did not consume the exact source artifact universe")
    normalized_consumed: list[dict[str, str]] = []
    seen_consumed: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_FIELDS:
            raise PhotorealDeviceDistillationRunnerError("consumed distillation source fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="consumed distillation source artifact path")
        if relative in seen_consumed:
            raise PhotorealDeviceDistillationRunnerError("distillation manifest repeats consumed source artifact")
        seen_consumed.add(relative)
        observed_sha = _sha(raw.get("sha256"), label="consumed distillation source artifact SHA-256")
        if source_universe.get(relative) != observed_sha:
            raise PhotorealDeviceDistillationRunnerError("distillation manifest consumed unauthorized source artifact bytes")
        normalized_consumed.append({"relative_path": relative, "sha256": observed_sha})
    if seen_consumed != set(source_universe):
        raise PhotorealDeviceDistillationRunnerError("distillation manifest omitted planned source artifacts")

    measurements = value.get("fidelity_delta_measurements")
    if not isinstance(measurements, list) or len(measurements) != len(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationRunnerError("distillation manifest fidelity delta universe is incomplete")
    normalized_measurements: list[dict[str, Any]] = []
    by_dimension: dict[str, dict[str, Any]] = {}
    for raw in measurements:
        if not isinstance(raw, Mapping) or set(raw) != MEASUREMENT_FIELDS:
            raise PhotorealDeviceDistillationRunnerError("fidelity delta measurement fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="fidelity delta dimension", maximum=80)
        if dimension not in FIDELITY_DIMENSIONS or dimension in by_dimension:
            raise PhotorealDeviceDistillationRunnerError("fidelity delta dimension is unsupported or repeated")
        item = {
            "dimension": dimension,
            "metric": _text(raw.get("metric"), label="fidelity delta metric", maximum=160),
            "value": _finite(raw.get("value"), label="fidelity delta value"),
            "unit": _text(raw.get("unit"), label="fidelity delta unit", maximum=80),
            "teacher_reference": _text(raw.get("teacher_reference"), label="teacher fidelity reference", maximum=512),
            "student_reference": _text(raw.get("student_reference"), label="student fidelity reference", maximum=512),
        }
        by_dimension[dimension] = item
    if set(by_dimension) != set(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationRunnerError("distillation manifest fidelity delta dimensions are incomplete")
    normalized_measurements = [by_dimension[item] for item in FIDELITY_DIMENSIONS]

    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealDeviceDistillationRunnerError("distillation manifest contains no student artifacts")
    normalized_artifacts: list[dict[str, Any]] = []
    listed: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealDeviceDistillationRunnerError("student artifact fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="student artifact kind", maximum=64)
        relative, path = _safe_child(output_dir, raw.get("relative_path"), label="student artifact path")
        if relative == "distillation-manifest.json" or relative in listed:
            raise PhotorealDeviceDistillationRunnerError("student artifact path is repeated or reserved")
        listed.add(relative)
        if not path.is_file():
            raise PhotorealDeviceDistillationRunnerError(f"student artifact is missing: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
            raise PhotorealDeviceDistillationRunnerError(f"student artifact size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if observed_sha != _sha(raw.get("sha256"), label="student artifact SHA-256"):
            raise PhotorealDeviceDistillationRunnerError(f"student artifact SHA-256 mismatch: {relative}")
        normalized_artifacts.append({"kind": kind, "relative_path": relative, "size_bytes": size, "sha256": observed_sha})
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "distillation-manifest.json"
    }
    if actual != listed:
        raise PhotorealDeviceDistillationRunnerError("student output artifact universe differs from distillation manifest")

    result = dict(value)
    result["consumed_distillation_source_artifacts"] = sorted(normalized_consumed, key=lambda item: item["relative_path"])
    result["fidelity_delta_measurements"] = normalized_measurements
    result["student_artifacts"] = sorted(normalized_artifacts, key=lambda item: item["relative_path"])
    return result


def _log_tail(path: Path, limit: int = 8000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def run_external_distillation(
    config: Mapping[str, Any],
    distillation_plan: Mapping[str, Any],
    *,
    animation_output_root: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = validate_distillation_config(config)
    request = build_distillation_request(config, distillation_plan, animation_output_root=animation_output_root)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealDeviceDistillationRunnerError(f"distillation workspace already exists: {root}")
    root.mkdir(parents=True)
    request_path = root / "request.json"
    output_dir = root / "output"
    log_path = root / "adapter.log"
    output_dir.mkdir()
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
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
        "--bodyrig-student-representation",
        config["student_representation"],
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealDeviceDistillationRunnerError(
            f"distillation adapter timed out after {config['timeout_seconds']} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealDeviceDistillationRunnerError(f"distillation adapter could not complete: {exc}{suffix}") from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealDeviceDistillationRunnerError(
            f"distillation adapter failed with exit code {completed.returncode}{suffix}"
        )
    manifest_path = output_dir / "distillation-manifest.json"
    if not manifest_path.is_file():
        raise PhotorealDeviceDistillationRunnerError("distillation adapter did not create distillation-manifest.json")
    manifest = _read_json(manifest_path, label="distillation manifest")
    return validate_distillation_result(manifest, request=request, output_dir=output_dir)


def run_external_distillation_files(
    config_path: str | Path,
    distillation_plan_path: str | Path,
    animation_output_root: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_distillation_config(config_path)
    plan = _read_json(distillation_plan_path, label="device distillation plan")
    return run_external_distillation(
        config,
        plan,
        animation_output_root=animation_output_root,
        workspace=workspace,
    )
