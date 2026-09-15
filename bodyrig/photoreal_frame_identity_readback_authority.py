from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identities,
)

BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
CALIBRATION_FORMAT = "bodyrig-photoreal-identity-calibration"
CALIBRATION_VERSION = 1
THRESHOLD_DERIVATION = "midpoint-positive-floor-negative-ceiling-v1"
MINIMUM_REQUIRED_SEPARATION_MARGIN = 0.05
MIN_NEGATIVE_OBSERVATIONS = 8
MIN_NEGATIVE_PERFORMERS = 2
_ROUNDING_TOLERANCE = 2e-9

_BANK_DIGEST_KEYS = (
    "format",
    "version",
    "performer_id",
    "extractor",
    "extractor_revision",
    "model_set_sha256",
    "embedding_dimension",
    "references",
    "centroid_embedding",
)
_CALIBRATION_DIGEST_KEYS = (
    "format",
    "version",
    "target_performer_id",
    "identity_bank_sha256",
    "model_set_sha256",
    "extractor",
    "extractor_revision",
    "embedding_dimension",
    "positive_reference_count",
    "positive_group_count",
    "negative_observation_count",
    "negative_performer_count",
    "positive_leave_group_out_cosine_min",
    "positive_leave_group_out_cosine_median",
    "positive_leave_group_out_cosine_max",
    "negative_to_target_centroid_cosine_min",
    "negative_to_target_centroid_cosine_median",
    "negative_to_target_centroid_cosine_max",
    "minimum_required_separation_margin",
    "observed_separation_margin",
    "threshold_derivation",
    "match_threshold",
    "match_threshold_calibrated",
    "identity_matching_authorized",
    "calibration_blockers",
)


class PhotorealFrameIdentityReadbackAuthorityError(PhotorealFrameIdentityAuthorityError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} must be a JSON string")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is invalid")
    return result


def _integer(
    value: Any,
    *,
    label: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} must be a JSON integer")
    if minimum is not None and value < minimum:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is below minimum")
    if maximum is not None and value > maximum:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is above maximum")
    return value


def _number(
    value: Any,
    *,
    label: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is below minimum")
    if maximum is not None and result > maximum:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} is above maximum")
    return result


def _embedding(value: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} dimension mismatch")
    vector = [_number(item, label=f"{label}[{index}]") for index, item in enumerate(value)]
    norm = math.sqrt(sum(item * item for item in vector))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealFrameIdentityReadbackAuthorityError(f"{label} has zero/invalid norm")
    return [item / norm for item in vector]


def _canonical_sha(value: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    try:
        raw = json.dumps(
            {key: value.get(key) for key in keys},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity authority input is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def canonical_identity_bank_sha256(bank: Mapping[str, Any]) -> str:
    return _canonical_sha(bank, _BANK_DIGEST_KEYS)


def canonical_identity_calibration_sha256(calibration: Mapping[str, Any]) -> str:
    return _canonical_sha(calibration, _CALIBRATION_DIGEST_KEYS)


def validate_identity_matching_readback(
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> tuple[int, list[float], float | None, bool]:
    bank_version = bank.get("version")
    if (
        bank.get("format") != BANK_FORMAT
        or isinstance(bank_version, bool)
        or not isinstance(bank_version, int)
        or bank_version != BANK_VERSION
    ):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank format/version mismatch")
    performer_id = _text(bank.get("performer_id"), label="identity bank performer id", maximum=256)
    extractor = _text(bank.get("extractor"), label="identity bank extractor", maximum=256)
    extractor_revision = _text(
        bank.get("extractor_revision"), label="identity bank extractor revision", maximum=256
    )
    model_sha = _sha(bank.get("model_set_sha256"), label="identity bank model-set SHA-256")
    dimension = _integer(
        bank.get("embedding_dimension"),
        label="identity bank embedding dimension",
        minimum=32,
        maximum=4096,
    )
    references = bank.get("references")
    if not isinstance(references, list) or len(references) < 4:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank references are invalid")
    reference_count = _integer(bank.get("reference_count"), label="identity bank reference count", minimum=4)
    if reference_count != len(references):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank reference count mismatch")
    source_group_count = _integer(bank.get("source_group_count"), label="identity bank source group count", minimum=2)
    groups: set[str] = set()
    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealFrameIdentityReadbackAuthorityError(f"identity bank reference[{index}] is invalid")
        groups.add(_text(raw.get("group_id"), label=f"identity bank reference[{index}] group id"))
        _embedding(raw.get("embedding"), dimension=dimension, label=f"identity bank reference[{index}] embedding")
    if source_group_count != len(groups):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank source group count mismatch")
    centroid = _embedding(bank.get("centroid_embedding"), dimension=dimension, label="identity bank centroid")
    if bank.get("train_only") is not True:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank is not train-only")
    if _integer(
        bank.get("evaluation_reference_count"),
        label="identity bank evaluation reference count",
        minimum=0,
        maximum=0,
    ) != 0:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank evaluation reference count must be zero")
    if bank.get("match_threshold_calibrated") is not False or bank.get("identity_matching_authorized") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank is already calibrated/authorized")
    if bank.get("identity_bank_ready_for_calibration") is not True:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank is not ready for calibration")
    if bank.get("teacher_training_authorized") is not False or bank.get("photoreal_acceptance_authority") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank crossed downstream authority")
    if bank.get("build_only") is not True or bank.get("runtime_dependency") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank authority boundary is invalid")
    if bank.get("production_activation") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank crossed production authority")
    expected_bank_sha = _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256")
    if canonical_identity_bank_sha256(bank) != expected_bank_sha:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity bank canonical digest mismatch at frame authority boundary")

    calibration_version = calibration.get("version")
    if (
        calibration.get("format") != CALIBRATION_FORMAT
        or isinstance(calibration_version, bool)
        or not isinstance(calibration_version, int)
        or calibration_version != CALIBRATION_VERSION
    ):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration format/version mismatch")
    if _text(calibration.get("target_performer_id"), label="identity calibration target performer", maximum=256) != performer_id:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration targets different performer")
    if _sha(calibration.get("identity_bank_sha256"), label="calibration identity bank SHA-256") != expected_bank_sha:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration targets different bank")
    if _sha(calibration.get("model_set_sha256"), label="calibration model-set SHA-256") != model_sha:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration targets different model set")
    if _text(calibration.get("extractor"), label="identity calibration extractor", maximum=256) != extractor:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration uses different extractor")
    if _text(calibration.get("extractor_revision"), label="identity calibration extractor revision", maximum=256) != extractor_revision:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration uses different extractor revision")
    if _integer(
        calibration.get("embedding_dimension"),
        label="identity calibration embedding dimension",
        minimum=32,
        maximum=4096,
    ) != dimension:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration embedding dimension mismatch")

    positive_reference_count = _integer(
        calibration.get("positive_reference_count"),
        label="identity calibration positive reference count",
        minimum=4,
    )
    if positive_reference_count != reference_count:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration positive reference count mismatch")
    positive_group_count = _integer(
        calibration.get("positive_group_count"),
        label="identity calibration positive group count",
        minimum=2,
    )
    if positive_group_count != source_group_count:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration positive group count mismatch")
    negative_observation_count = _integer(
        calibration.get("negative_observation_count"),
        label="identity calibration negative observation count",
        minimum=1,
    )
    negative_performer_count = _integer(
        calibration.get("negative_performer_count"),
        label="identity calibration negative performer count",
        minimum=1,
    )

    positive_min = _number(
        calibration.get("positive_leave_group_out_cosine_min"),
        label="identity calibration positive cosine min",
        minimum=-1.0,
        maximum=1.0,
    )
    positive_median = _number(
        calibration.get("positive_leave_group_out_cosine_median"),
        label="identity calibration positive cosine median",
        minimum=-1.0,
        maximum=1.0,
    )
    positive_max = _number(
        calibration.get("positive_leave_group_out_cosine_max"),
        label="identity calibration positive cosine max",
        minimum=-1.0,
        maximum=1.0,
    )
    negative_min = _number(
        calibration.get("negative_to_target_centroid_cosine_min"),
        label="identity calibration negative cosine min",
        minimum=-1.0,
        maximum=1.0,
    )
    negative_median = _number(
        calibration.get("negative_to_target_centroid_cosine_median"),
        label="identity calibration negative cosine median",
        minimum=-1.0,
        maximum=1.0,
    )
    negative_max = _number(
        calibration.get("negative_to_target_centroid_cosine_max"),
        label="identity calibration negative cosine max",
        minimum=-1.0,
        maximum=1.0,
    )
    if not positive_min <= positive_median <= positive_max:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration positive cosine ordering is invalid")
    if not negative_min <= negative_median <= negative_max:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration negative cosine ordering is invalid")

    margin = _number(
        calibration.get("minimum_required_separation_margin"),
        label="identity calibration minimum separation margin",
    )
    if margin != MINIMUM_REQUIRED_SEPARATION_MARGIN:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration minimum separation margin changed")
    observed_margin = _number(
        calibration.get("observed_separation_margin"),
        label="identity calibration observed separation margin",
        minimum=-2.0,
        maximum=2.0,
    )
    if abs(observed_margin - (positive_min - negative_max)) > _ROUNDING_TOLERANCE:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration observed separation is inconsistent")
    if calibration.get("threshold_derivation") != THRESHOLD_DERIVATION:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration threshold derivation mismatch")

    authorized = calibration.get("identity_matching_authorized")
    calibrated = calibration.get("match_threshold_calibrated")
    if not isinstance(authorized, bool) or not isinstance(calibrated, bool):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration matching authority must be boolean")
    if authorized != calibrated:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration matching/threshold authority is inconsistent")
    expected_authorized = (
        negative_observation_count >= MIN_NEGATIVE_OBSERVATIONS
        and negative_performer_count >= MIN_NEGATIVE_PERFORMERS
        and observed_margin >= MINIMUM_REQUIRED_SEPARATION_MARGIN
    )
    if authorized != expected_authorized:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration matching authority contradicts calibration evidence")

    blockers = calibration.get("calibration_blockers")
    if not isinstance(blockers, list) or any(not isinstance(item, str) or not item.strip() for item in blockers):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration blockers are invalid")
    if len(set(blockers)) != len(blockers):
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration blockers are duplicated")
    threshold_raw = calibration.get("match_threshold")
    threshold: float | None
    if authorized:
        threshold = _number(threshold_raw, label="identity match threshold", minimum=-1.0, maximum=1.0)
        expected_threshold = (positive_min + negative_max) / 2.0
        if abs(threshold - expected_threshold) > _ROUNDING_TOLERANCE:
            raise PhotorealFrameIdentityReadbackAuthorityError("identity match threshold contradicts calibration evidence")
        if blockers:
            raise PhotorealFrameIdentityReadbackAuthorityError("authorized identity calibration still has blockers")
    else:
        if threshold_raw is not None:
            raise PhotorealFrameIdentityReadbackAuthorityError("unauthorized identity calibration must not expose threshold")
        if not blockers:
            raise PhotorealFrameIdentityReadbackAuthorityError("unauthorized identity calibration must retain blockers")
        threshold = None

    if calibration.get("calibration_data_teacher_input") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration crossed calibration-data authority")
    if calibration.get("teacher_training_authorized") is not False or calibration.get("photoreal_acceptance_authority") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration crossed downstream authority")
    if calibration.get("build_only") is not True or calibration.get("runtime_dependency") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration authority boundary is invalid")
    if calibration.get("production_activation") is not False:
        raise PhotorealFrameIdentityReadbackAuthorityError("identity calibration crossed production authority")

    expected_calibration_sha = _sha(
        calibration.get("identity_calibration_sha256"), label="identity calibration SHA-256"
    )
    if canonical_identity_calibration_sha256(calibration) != expected_calibration_sha:
        raise PhotorealFrameIdentityReadbackAuthorityError(
            "identity calibration canonical digest mismatch at frame authority boundary"
        )
    return dimension, centroid, threshold, authorized


def authorize_frame_identity_files_strict(
    plan_path: str | Path,
    measurements_path: str | Path,
    bank_path: str | Path,
    calibration_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    measurements = _read_json(measurements_path, label="photoreal frame measurements")
    bank = _read_json(bank_path, label="photoreal identity bank")
    calibration = _read_json(calibration_path, label="photoreal identity calibration")
    validate_identity_matching_readback(bank, calibration)
    result = authorize_frame_identities(plan, measurements, bank, calibration)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIdentityReadbackAuthorityError(f"frame identity authority output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
