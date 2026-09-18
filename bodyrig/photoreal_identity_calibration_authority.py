from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_identity_calibration import (
    PhotorealIdentityCalibrationError,
    build_identity_calibration,
)
from .photoreal_identity_negative_verify import (
    INVENTORY_FORMAT,
    INVENTORY_VERSION,
    LABEL_AUTHORITY,
    PhotorealIdentityNegativeVerifyError,
    canonical_identity_negative_inventory_sha256,
)

PLAN_FORMAT = "bodyrig-photoreal-identity-calibration-plan"
PLAN_VERSION = 1
BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
OBSERVATIONS_FORMAT = "bodyrig-photoreal-identity-negative-observations"
OBSERVATIONS_VERSION = 1
_EYES = {"mono", "left", "right"}


class PhotorealIdentityCalibrationAuthorityError(PhotorealIdentityCalibrationError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON string")
    if len(value) > maximum or (not allow_empty and not value.strip()):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    return result


def _integer(
    value: Any,
    *,
    label: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON integer")
    if minimum is not None and value < minimum:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is below minimum")
    if maximum is not None and value > maximum:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is above maximum")
    return value


def _number(value: Any, *, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is below minimum")
    if maximum is not None and number > maximum:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is above maximum")
    return number


def _timestamp(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    return _number(value, label=label, minimum=0.0)


def _embedding(value: Any, *, dimension: int, label: str) -> None:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} dimension mismatch")
    for index, item in enumerate(value):
        _number(item, label=f"{label}[{index}]")


def _eye(value: Any, *, label: str) -> str:
    eye = _text(value, label=label, maximum=16)
    if eye not in _EYES:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    return eye


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON object")
    return value


def _require_list(value: Any, *, label: str, minimum: int = 1) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a non-empty JSON array")
    return value


def validate_calibration_point_of_use_types(
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
) -> None:
    """Reject JSON type confusion before the calibration core can coerce values."""
    if bank.get("format") != BANK_FORMAT or _integer(bank.get("version"), label="identity bank version") != BANK_VERSION:
        raise PhotorealIdentityCalibrationAuthorityError("identity bank format/version mismatch")
    _text(bank.get("performer_id"), label="identity bank performer id", maximum=256)
    _text(bank.get("performer_name"), label="identity bank performer name", allow_empty=True)
    _text(bank.get("extractor"), label="identity bank extractor", maximum=256)
    _text(bank.get("extractor_revision"), label="identity bank extractor revision", maximum=256)
    _sha(bank.get("model_set_sha256"), label="identity bank model-set SHA-256")
    _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256")
    dimension = _integer(bank.get("embedding_dimension"), label="identity bank embedding dimension", minimum=32, maximum=4096)
    references = _require_list(bank.get("references"), label="identity bank references", minimum=4)
    reference_count = _integer(bank.get("reference_count"), label="identity bank reference count", minimum=4)
    if reference_count != len(references):
        raise PhotorealIdentityCalibrationAuthorityError("identity bank reference count mismatch")
    source_group_count = _integer(bank.get("source_group_count"), label="identity bank source group count", minimum=2)
    groups: set[str] = set()
    for index, raw in enumerate(references):
        reference = _require_mapping(raw, label=f"identity bank reference[{index}]")
        _text(reference.get("source_key"), label=f"identity bank reference[{index}] source key")
        _sha(reference.get("source_sha256"), label=f"identity bank reference[{index}] source SHA-256")
        group = _text(reference.get("group_id"), label=f"identity bank reference[{index}] group id")
        groups.add(group)
        _timestamp(reference.get("timestamp_seconds"), label=f"identity bank reference[{index}] timestamp")
        _eye(reference.get("eye"), label=f"identity bank reference[{index}] eye")
        _sha(reference.get("frame_sha256"), label=f"identity bank reference[{index}] frame SHA-256")
        _embedding(reference.get("embedding"), dimension=dimension, label=f"identity bank reference[{index}] embedding")
    if source_group_count != len(groups):
        raise PhotorealIdentityCalibrationAuthorityError("identity bank source group count mismatch")
    _embedding(bank.get("centroid_embedding"), dimension=dimension, label="identity bank centroid embedding")
    for field in (
        "reference_to_centroid_cosine_min",
        "reference_to_centroid_cosine_median",
        "reference_to_centroid_cosine_max",
    ):
        _number(bank.get(field), label=f"identity bank {field}", minimum=-1.0, maximum=1.0)
    if _integer(bank.get("evaluation_reference_count"), label="identity bank evaluation reference count", minimum=0) != 0:
        raise PhotorealIdentityCalibrationAuthorityError("identity bank evaluation reference count must be zero")

    if plan.get("format") != PLAN_FORMAT or _integer(plan.get("version"), label="identity calibration plan version") != PLAN_VERSION:
        raise PhotorealIdentityCalibrationAuthorityError("identity calibration plan format/version mismatch")
    _text(plan.get("target_performer_id"), label="identity calibration plan target performer", maximum=256)
    _sha(plan.get("identity_bank_sha256"), label="identity calibration plan bank SHA-256")
    _sha(plan.get("negative_inventory_sha256"), label="identity calibration plan negative inventory SHA-256")
    _sha(plan.get("model_set_sha256"), label="identity calibration plan model-set SHA-256")
    _text(plan.get("extractor"), label="identity calibration plan extractor", maximum=256)
    _text(plan.get("extractor_revision"), label="identity calibration plan extractor revision", maximum=256)
    if _integer(plan.get("embedding_dimension"), label="identity calibration plan embedding dimension", minimum=32, maximum=4096) != dimension:
        raise PhotorealIdentityCalibrationAuthorityError("identity calibration plan embedding dimension mismatch")
    _integer(plan.get("negative_performer_count"), label="identity calibration plan negative performer count", minimum=2)
    planned_sources = _require_list(plan.get("sources"), label="identity calibration plan sources", minimum=2)
    if _integer(plan.get("source_count"), label="identity calibration plan source count", minimum=2) != len(planned_sources):
        raise PhotorealIdentityCalibrationAuthorityError("identity calibration plan source count mismatch")
    _integer(plan.get("planned_negative_observation_count"), label="identity calibration planned observation count", minimum=2)
    _integer(plan.get("video_timestamps_per_source"), label="identity calibration video timestamps per source", minimum=1)
    for index, raw in enumerate(planned_sources):
        source = _require_mapping(raw, label=f"identity calibration source[{index}]")
        _text(source.get("source_key"), label=f"identity calibration source[{index}] key")
        _sha(source.get("source_sha256"), label=f"identity calibration source[{index}] SHA-256")
        _text(source.get("resolved_path"), label=f"identity calibration source[{index}] resolved path")
        _text(source.get("subject_performer_id"), label=f"identity calibration source[{index}] subject performer", maximum=256)
        _text(source.get("subject_performer_name"), label=f"identity calibration source[{index}] subject name", allow_empty=True)
        _text(source.get("target_performer_id"), label=f"identity calibration source[{index}] target performer", maximum=256)
        _text(source.get("kind"), label=f"identity calibration source[{index}] kind", maximum=16)
        _text(source.get("source_binding"), label=f"identity calibration source[{index}] binding", maximum=64)
        _text(source.get("projection"), label=f"identity calibration source[{index}] projection", maximum=128)
        _text(source.get("stereo_layout"), label=f"identity calibration source[{index}] stereo layout", maximum=128)
        _text(source.get("decode_mode"), label=f"identity calibration source[{index}] decode mode", maximum=128)
        samples = _require_list(source.get("samples"), label=f"identity calibration source[{index}] samples")
        if _integer(source.get("sample_count"), label=f"identity calibration source[{index}] sample count", minimum=1) != len(samples):
            raise PhotorealIdentityCalibrationAuthorityError("identity calibration source sample count mismatch")
        for sample_index, raw_sample in enumerate(samples):
            sample = _require_mapping(raw_sample, label=f"identity calibration source[{index}] sample[{sample_index}]")
            _timestamp(sample.get("timestamp_seconds"), label=f"identity calibration source[{index}] sample[{sample_index}] timestamp")
            _eye(sample.get("eye"), label=f"identity calibration source[{index}] sample[{sample_index}] eye")

    if (
        negative_observations.get("format") != OBSERVATIONS_FORMAT
        or _integer(negative_observations.get("version"), label="identity negative observations version") != OBSERVATIONS_VERSION
    ):
        raise PhotorealIdentityCalibrationAuthorityError("identity negative observations format/version mismatch")
    _text(negative_observations.get("target_performer_id"), label="identity negative observations target performer", maximum=256)
    _sha(negative_observations.get("identity_bank_sha256"), label="identity negative observations bank SHA-256")
    _text(negative_observations.get("extractor"), label="identity negative observations extractor", maximum=256)
    _text(negative_observations.get("extractor_revision"), label="identity negative observations extractor revision", maximum=256)
    _sha(negative_observations.get("model_set_sha256"), label="identity negative observations model-set SHA-256")
    if _integer(negative_observations.get("embedding_dimension"), label="identity negative observations embedding dimension", minimum=32, maximum=4096) != dimension:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative observations embedding dimension mismatch")
    observations = _require_list(negative_observations.get("observations"), label="identity negative observations")
    for index, raw in enumerate(observations):
        observation = _require_mapping(raw, label=f"identity negative observation[{index}]")
        _text(observation.get("source_key"), label=f"identity negative observation[{index}] source key")
        _sha(observation.get("source_sha256"), label=f"identity negative observation[{index}] source SHA-256")
        _text(observation.get("subject_performer_id"), label=f"identity negative observation[{index}] subject performer", maximum=256)
        _timestamp(observation.get("timestamp_seconds"), label=f"identity negative observation[{index}] timestamp")
        _eye(observation.get("eye"), label=f"identity negative observation[{index}] eye")
        _sha(observation.get("frame_sha256"), label=f"identity negative observation[{index}] frame SHA-256")
        _embedding(observation.get("embedding"), dimension=dimension, label=f"identity negative observation[{index}] embedding")


def validate_negative_inventory_binding(
    negative_inventory: Mapping[str, Any],
    plan: Mapping[str, Any],
    bank: Mapping[str, Any],
) -> str:
    version = negative_inventory.get("version")
    if (
        negative_inventory.get("format") != INVENTORY_FORMAT
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != INVENTORY_VERSION
    ):
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory format/version mismatch")
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealIdentityCalibrationAuthorityError("identity calibration plan format/version mismatch")
    if negative_inventory.get("label_authority") != LABEL_AUTHORITY:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory label authority mismatch")
    if negative_inventory.get("calibration_only") is not True or negative_inventory.get("photoreal_teacher_input") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed calibration/teacher boundary")
    if negative_inventory.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed training authority")
    if negative_inventory.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed matching authority")
    if negative_inventory.get("build_only") is not True or negative_inventory.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory build/runtime authority is invalid")
    if negative_inventory.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed production authority")

    target = negative_inventory.get("target_performer_id")
    if not isinstance(target, str) or not target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory target performer is invalid")
    bank_target = bank.get("performer_id")
    if not isinstance(bank_target, str) or target.strip() != bank_target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory/bank performer mismatch")
    if plan.get("target_performer_id") != target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory/plan performer mismatch")

    expected = _sha(plan.get("negative_inventory_sha256"), label="plan negative inventory SHA-256")
    try:
        observed = canonical_identity_negative_inventory_sha256(negative_inventory)
    except PhotorealIdentityNegativeVerifyError as exc:
        raise PhotorealIdentityCalibrationAuthorityError(str(exc)) from exc
    if observed != expected:
        raise PhotorealIdentityCalibrationAuthorityError(
            "identity negative inventory canonical digest mismatch at calibration authority boundary"
        )
    return observed


def build_identity_calibration_authorized(
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
    negative_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    validate_calibration_point_of_use_types(bank, plan, negative_observations)
    validate_negative_inventory_binding(negative_inventory, plan, bank)
    return build_identity_calibration(bank, plan, negative_observations)


def build_identity_calibration_authorized_files(
    bank_path: str | Path,
    plan_path: str | Path,
    negative_observations_path: str | Path,
    negative_inventory_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    bank = _read_json(bank_path, label="identity bank")
    plan = _read_json(plan_path, label="identity calibration plan")
    observations = _read_json(negative_observations_path, label="identity negative observations")
    inventory = _read_json(negative_inventory_path, label="identity negative inventory")
    result = build_identity_calibration_authorized(bank, plan, observations, inventory)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationAuthorityError(f"identity calibration output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
