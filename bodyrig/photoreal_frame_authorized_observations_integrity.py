from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-frame-authorized-observations"
VERSION = 1
DIGEST_FIELD = "authorized_observations_sha256"
EXPECTED_KEYS = frozenset(
    {
        "format",
        "version",
        "performer_id",
        "analyzer",
        "analyzer_revision",
        "analyzer_model_set_sha256",
        "identity_bank_sha256",
        "identity_calibration_sha256",
        DIGEST_FIELD,
        "identity_matching_calibrated",
        "identity_match_threshold",
        "identity_ambiguous_sample_count",
        "observations",
        "identity_authority_is_core_derived",
        "multi_candidate_identity_safe",
        "photoreal_acceptance_authority",
        "build_only",
        "production_activation",
    }
)


class PhotorealAuthorizedObservationsIntegrityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAuthorizedObservationsIntegrityError(f"{label} must be a JSON string")
    result = value.strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealAuthorizedObservationsIntegrityError(f"{label} is invalid")
    return result


def _canonical_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != DIGEST_FIELD}


def canonical_authorized_observations_sha256(value: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(
            _canonical_payload(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations are not canonical JSON"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def validate_authorized_observations_integrity(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations must be a JSON object"
        )
    keys = set(value)
    if keys != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - keys)
        extra = sorted(keys - EXPECTED_KEYS)
        raise PhotorealAuthorizedObservationsIntegrityError(
            f"authorized frame observations key set mismatch (missing={missing}, extra={extra})"
        )

    version = value.get("version")
    if (
        value.get("format") != FORMAT
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != VERSION
    ):
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations format/version mismatch"
        )

    for field in (
        "performer_id",
        "analyzer",
        "analyzer_revision",
    ):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise PhotorealAuthorizedObservationsIntegrityError(
                f"authorized frame observations {field} must be a non-empty JSON string"
            )
    for field in (
        "analyzer_model_set_sha256",
        "identity_bank_sha256",
        "identity_calibration_sha256",
    ):
        _sha(value.get(field), label=f"authorized frame observations {field}")

    if value.get("identity_authority_is_core_derived") is not True:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations lack core-derived identity authority"
        )
    if value.get("multi_candidate_identity_safe") is not True:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations lack multi-candidate identity safety"
        )
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations crossed photoreal authority"
        )
    if value.get("build_only") is not True or value.get("production_activation") is not False:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations crossed build/production authority"
        )

    calibrated = value.get("identity_matching_calibrated")
    if not isinstance(calibrated, bool):
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations calibrated-matching flag must be boolean"
        )
    threshold = value.get("identity_match_threshold")
    if calibrated:
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise PhotorealAuthorizedObservationsIntegrityError(
                "authorized frame observations calibrated threshold must be a JSON number"
            )
        numeric_threshold = float(threshold)
        if not math.isfinite(numeric_threshold) or not -1.0 <= numeric_threshold <= 1.0:
            raise PhotorealAuthorizedObservationsIntegrityError(
                "authorized frame observations calibrated threshold is invalid"
            )
    elif threshold is not None:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "uncalibrated authorized frame observations must have null threshold"
        )

    ambiguous_count = value.get("identity_ambiguous_sample_count")
    if isinstance(ambiguous_count, bool) or not isinstance(ambiguous_count, int) or ambiguous_count < 0:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations ambiguous-sample count must be a nonnegative JSON integer"
        )
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations contain no observations"
        )

    expected = _sha(value.get(DIGEST_FIELD), label="authorized frame observations SHA-256")
    observed = canonical_authorized_observations_sha256(value)
    if observed != expected:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations canonical digest mismatch"
        )
    return observed


def seal_authorized_observations(value: Mapping[str, Any]) -> dict[str, Any]:
    if DIGEST_FIELD in value:
        raise PhotorealAuthorizedObservationsIntegrityError(
            "authorized frame observations are already sealed"
        )
    result = dict(value)
    result[DIGEST_FIELD] = canonical_authorized_observations_sha256(result)
    validate_authorized_observations_integrity(result)
    return result
