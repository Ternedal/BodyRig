from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .logged_process import LoggedProcessError, run_logged_process

CONFIG_FORMAT = "bodyrig-photoreal-identity-extractor-config"
CONFIG_VERSION = 1
PLAN_FORMAT = "bodyrig-photoreal-identity-calibration-plan"
PLAN_VERSION = 1
MODEL_SET_FORMAT = "bodyrig-photoreal-analyzer-model-set"
MODEL_SET_VERSION = 1
REQUEST_FORMAT = "bodyrig-photoreal-identity-calibration-extractor-request"
REQUEST_VERSION = 1
RESULT_FORMAT = "bodyrig-photoreal-identity-negative-observations"
RESULT_VERSION = 1
_OPTIONAL_AUTHORITY_FIELDS = {
    "identity_matching_authority",
    "teacher_training_authorized",
    "photoreal_acceptance_authority",
}
_QUALITY_FIELDS = {
    "candidate_id",
    "candidate_count",
    "person_detected",
    "width",
    "height",
    "view_bin",
    "face_visibility",
    "full_body_visibility",
    "person_fraction",
    "sharpness",
    "motion",
    "occlusion",
    "identity_measurement_status",
    "identity_measurement_reason",
}
_VALID_VIEW_BINS = {
    "front",
    "three-quarter-right",
    "three-quarter-left",
    "profile-right",
    "profile-left",
    "rear",
    "unknown",
}


class PhotorealIdentityCalibrationExtractorError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityCalibrationExtractorError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationExtractorError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationExtractorError(f"{label} is invalid")
    return result


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealIdentityCalibrationExtractorError(f"{label} is invalid")
    return result


def _validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    required = {"format", "version", "adapter", "revision", "model_set_sha256", "command", "timeout_seconds"}
    if set(config) != required:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration extractor config fields must match v1 exactly")
    version = config.get("version")
    if config.get("format") != CONFIG_FORMAT or isinstance(version, bool) or version != CONFIG_VERSION:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration extractor config format/version mismatch")
    adapter = _text(config.get("adapter"), label="identity extractor adapter", maximum=80)
    if any(not (ch.isalnum() or ch in "._-") for ch in adapter):
        raise PhotorealIdentityCalibrationExtractorError("identity extractor adapter is invalid")
    revision = _text(config.get("revision"), label="identity extractor revision", maximum=160)
    model_set_sha256 = _sha(config.get("model_set_sha256"), label="identity extractor model-set SHA-256")
    command = config.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
    ):
        raise PhotorealIdentityCalibrationExtractorError("identity extractor command must be a non-empty argv list")
    timeout = config.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise PhotorealIdentityCalibrationExtractorError("identity extractor timeout_seconds must be in 1..86400")
    return {
        "format": CONFIG_FORMAT,
        "version": CONFIG_VERSION,
        "adapter": adapter,
        "revision": revision,
        "model_set_sha256": model_set_sha256,
        "command": list(command),
        "timeout_seconds": timeout,
    }


def load_calibration_extractor_config(path: str | Path) -> dict[str, Any]:
    return _validate_config(_read_json(path, label="identity calibration extractor config"))


def _validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan format/version mismatch")
    if plan.get("negative_embedding_extraction_required") is not True or plan.get("calibration_only") is not True:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan does not authorize calibration measurement")
    if plan.get("identity_matching_authorized") is not False or plan.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan crossed matching/training authority")
    if plan.get("photoreal_acceptance_authority") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan crossed photoreal authority")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan crossed production authority")
    sources = plan.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan contains no sources")


def _validate_model_set(model_set: Mapping[str, Any]) -> str:
    if model_set.get("format") != MODEL_SET_FORMAT or model_set.get("version") != MODEL_SET_VERSION:
        raise PhotorealIdentityCalibrationExtractorError("identity model-set format/version mismatch")
    if model_set.get("build_only") is not True or model_set.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity model-set authority boundary is invalid")
    if model_set.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity model-set crossed production authority")
    return _sha(model_set.get("model_set_sha256"), label="identity model-set SHA-256")


def build_calibration_extractor_request(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    model_set: Mapping[str, Any],
) -> dict[str, Any]:
    config = _validate_config(config)
    _validate_plan(plan)
    model_set_sha256 = _validate_model_set(model_set)
    if config["model_set_sha256"] != model_set_sha256:
        raise PhotorealIdentityCalibrationExtractorError("identity extractor config targets a different model set")
    if _sha(plan.get("model_set_sha256"), label="calibration plan model-set SHA-256") != model_set_sha256:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan targets a different model set")
    if plan.get("extractor") != config["adapter"] or plan.get("extractor_revision") != config["revision"]:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration plan/extractor provenance mismatch")
    return {
        "format": REQUEST_FORMAT,
        "version": REQUEST_VERSION,
        "target_performer_id": _text(plan.get("target_performer_id"), label="target performer id", maximum=256),
        "identity_bank_sha256": _sha(plan.get("identity_bank_sha256"), label="identity bank SHA-256"),
        "adapter": config["adapter"],
        "revision": config["revision"],
        "model_set_sha256": model_set_sha256,
        "embedding_dimension": int(plan.get("embedding_dimension")),
        "sources": plan["sources"],
        "measurement_only": True,
        "calibration_only": True,
        "identity_matching_authority": False,
        "teacher_training_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _log_tail(path: Path, limit: int = 6000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw[-limit:].decode("utf-8", errors="replace").strip()


def _validate_quality_metadata(observation: Mapping[str, Any]) -> None:
    present = _QUALITY_FIELDS.intersection(observation)
    if not present:
        return
    if present != _QUALITY_FIELDS:
        missing = sorted(_QUALITY_FIELDS.difference(observation))
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observation quality metadata is incomplete: "
            + ", ".join(missing)
        )
    candidate_id = observation["candidate_id"]
    if (
        not isinstance(candidate_id, str)
        or not candidate_id
        or len(candidate_id) > 128
        or any(not (ch.isalnum() or ch in "._-") for ch in candidate_id)
    ):
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observation candidate_id is invalid"
        )
    candidate_count = observation["candidate_count"]
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count != 1
    ):
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observation candidate_count must preserve the single-person rule"
        )
    if observation["person_detected"] is not True:
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observation quality metadata must describe a detected person"
        )
    for field in ("width", "height"):
        value = observation[field]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PhotorealIdentityCalibrationExtractorError(
                f"identity negative observation {field} is invalid"
            )
    if observation["view_bin"] not in _VALID_VIEW_BINS:
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observation view_bin is invalid"
        )
    for field in (
        "face_visibility",
        "full_body_visibility",
        "person_fraction",
        "sharpness",
        "motion",
        "occlusion",
    ):
        value = observation[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PhotorealIdentityCalibrationExtractorError(
                f"identity negative observation {field} is invalid"
            )
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise PhotorealIdentityCalibrationExtractorError(
                f"identity negative observation {field} is invalid"
            ) from exc
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise PhotorealIdentityCalibrationExtractorError(
                f"identity negative observation {field} is outside 0..1"
            )
    if observation["identity_measurement_status"] != "available":
        raise PhotorealIdentityCalibrationExtractorError(
            "accepted identity negative observation must have available identity measurement"
        )
    if observation["identity_measurement_reason"] != "embedding-available":
        raise PhotorealIdentityCalibrationExtractorError(
            "accepted identity negative observation measurement reason is invalid"
        )


def validate_calibration_extractor_result(
    value: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "target_performer_id",
        "identity_bank_sha256",
        "extractor",
        "extractor_revision",
        "model_set_sha256",
        "embedding_dimension",
        "observations",
        "calibration_only",
        "build_only",
        "production_activation",
    }
    fields = set(value)
    if not required.issubset(fields) or fields.difference(required, _OPTIONAL_AUTHORITY_FIELDS):
        raise PhotorealIdentityCalibrationExtractorError(
            "identity negative observations fields must match backward-compatible v1"
        )
    version = value.get("version")
    if value.get("format") != RESULT_FORMAT or isinstance(version, bool) or version != RESULT_VERSION:
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations format/version mismatch")
    if str(value.get("target_performer_id") or "") != str(plan.get("target_performer_id") or ""):
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations target mismatch")
    if _sha(value.get("identity_bank_sha256"), label="result identity bank SHA-256") != _sha(
        plan.get("identity_bank_sha256"), label="plan identity bank SHA-256"
    ):
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations bank mismatch")
    if value.get("extractor") != config["adapter"] or value.get("extractor_revision") != config["revision"]:
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations extractor provenance mismatch")
    if _sha(value.get("model_set_sha256"), label="result model-set SHA-256") != config["model_set_sha256"]:
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations model-set mismatch")
    dimension = value.get("embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension != int(plan.get("embedding_dimension")):
        raise PhotorealIdentityCalibrationExtractorError("identity negative observations embedding dimension mismatch")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration extractor returned no observations")
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise PhotorealIdentityCalibrationExtractorError(
                "identity calibration extractor returned a non-object observation"
            )
        _validate_quality_metadata(observation)
    for field in _OPTIONAL_AUTHORITY_FIELDS:
        if field in value and value[field] is not False:
            raise PhotorealIdentityCalibrationExtractorError(
                f"identity calibration extractor crossed {field}"
            )
    if value.get("calibration_only") is not True or value.get("build_only") is not True:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration extractor crossed calibration/build authority")
    if value.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationExtractorError("identity calibration extractor crossed production authority")
    return dict(value)


def run_external_calibration_extractor(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    model_set: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    config = _validate_config(config)
    request = build_calibration_extractor_request(config, plan, model_set)
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealIdentityCalibrationExtractorError(f"identity calibration workspace already exists: {root}")
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
        "--bodyrig-request", str(request_path),
        "--bodyrig-output", str(output_dir),
        "--bodyrig-adapter", config["adapter"],
        "--bodyrig-revision", config["revision"],
        "--bodyrig-model-set-sha256", config["model_set_sha256"],
        "--bodyrig-identity-bank-sha256", request["identity_bank_sha256"],
    ]
    try:
        completed = run_logged_process(invoke, log_path=log_path, timeout_seconds=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealIdentityCalibrationExtractorError(
            f"identity calibration extractor timed out after {config['timeout_seconds']} seconds{suffix}"
        ) from exc
    except (OSError, LoggedProcessError) as exc:
        detail = _log_tail(log_path)
        suffix = f" | log tail: {detail}" if detail else ""
        raise PhotorealIdentityCalibrationExtractorError(
            f"identity calibration extractor process could not complete: {exc}{suffix}"
        ) from exc
    if completed.returncode != 0:
        detail = _log_tail(log_path)
        suffix = f": {detail}" if detail else ""
        raise PhotorealIdentityCalibrationExtractorError(
            f"identity calibration extractor failed with exit code {completed.returncode}{suffix}"
        )
    children = list(output_dir.iterdir())
    if {item.name for item in children} != {"negative-observations.json"} or any(not item.is_file() for item in children):
        raise PhotorealIdentityCalibrationExtractorError(
            "identity calibration extractor output must contain exactly negative-observations.json"
        )
    result = _read_json(output_dir / "negative-observations.json", label="identity negative observations")
    return validate_calibration_extractor_result(result, plan=plan, config=config)


def run_external_calibration_extractor_files(
    config_path: str | Path,
    plan_path: str | Path,
    model_set_path: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    config = load_calibration_extractor_config(config_path)
    plan = _read_json(plan_path, label="identity calibration plan")
    model_set = _read_json(model_set_path, label="identity model set")
    return run_external_calibration_extractor(config, plan, model_set, workspace=workspace)
