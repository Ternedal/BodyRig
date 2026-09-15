from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-frame-index"
VERSION = 1
DIGEST_FIELD = "frame_index_sha256"
SOURCE_DIGEST_FIELD = "source_authorized_observations_sha256"
EXPECTED_KEYS = frozenset(
    {
        "format",
        "version",
        "performer_id",
        "performer_name",
        "analyzer",
        "analyzer_revision",
        "analyzer_model_set_sha256",
        "identity_bank_sha256",
        "identity_calibration_sha256",
        "identity_matching_calibrated",
        "identity_match_threshold",
        "identity_authority_is_core_derived",
        "multi_candidate_identity_safe",
        "identity_ambiguous_sample_count",
        "source_count",
        "observed_source_count",
        "observation_count",
        "eligible_train_observation_count",
        "eligible_evaluation_observation_count",
        "perceptual_hash_algorithm_contract",
        "cross_split_max_hamming_distance",
        "cross_split_near_duplicate_count",
        "cross_split_near_duplicates",
        "held_out_view_coverage_required",
        "held_out_view_coverage_observed",
        "held_out_view_coverage_missing",
        "rear_view_source_observable",
        "thresholds",
        "observations",
        "teacher_training_authorized",
        "training_blockers",
        "photoreal_acceptance_authority",
        "human_visual_acceptance_required",
        "build_only",
        "runtime_dependency",
        "production_activation",
        SOURCE_DIGEST_FIELD,
        DIGEST_FIELD,
    }
)


class PhotorealFrameIndexIntegrityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealFrameIndexIntegrityError(f"{label} must be a JSON string")
    result = value.strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealFrameIndexIntegrityError(f"{label} is invalid")
    return result


def _count(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PhotorealFrameIndexIntegrityError(f"{label} must be a nonnegative JSON integer")
    return value


def _canonical_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != DIGEST_FIELD}


def canonical_frame_index_sha256(value: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(
            _canonical_payload(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def validate_frame_index_integrity(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index must be a JSON object")
    keys = set(value)
    if keys != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - keys)
        extra = sorted(keys - EXPECTED_KEYS)
        raise PhotorealFrameIndexIntegrityError(
            f"photoreal frame index key set mismatch (missing={missing}, extra={extra})"
        )

    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or not isinstance(version, int) or version != VERSION:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index format/version mismatch")

    for field in ("performer_id", "analyzer", "analyzer_revision"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise PhotorealFrameIndexIntegrityError(f"photoreal frame index {field} must be a non-empty JSON string")
    for field in (
        "analyzer_model_set_sha256",
        "identity_bank_sha256",
        "identity_calibration_sha256",
        SOURCE_DIGEST_FIELD,
    ):
        _sha(value.get(field), label=f"photoreal frame index {field}")

    if value.get("identity_authority_is_core_derived") is not True:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index lacks core-derived identity authority")
    if value.get("multi_candidate_identity_safe") is not True:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index lacks multi-candidate identity safety")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index crossed photoreal acceptance authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index human-review boundary is invalid")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index build/runtime boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index crossed production authority")
    if not isinstance(value.get("teacher_training_authorized"), bool):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index teacher authorization must be boolean")

    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index contains no observations")
    observation_count = _count(value.get("observation_count"), label="photoreal frame index observation_count")
    if observation_count != len(observations):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index observation count mismatch")

    source_count = _count(value.get("source_count"), label="photoreal frame index source_count")
    observed_source_count = _count(
        value.get("observed_source_count"), label="photoreal frame index observed_source_count"
    )
    observed_sources = {
        item.get("source_key")
        for item in observations
        if isinstance(item, Mapping) and isinstance(item.get("source_key"), str) and item.get("source_key")
    }
    if observed_source_count != len(observed_sources) or source_count != observed_source_count:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index source counts are inconsistent")

    eligible_train = sum(
        1
        for item in observations
        if isinstance(item, Mapping) and item.get("eligible_for_teacher") is True and item.get("split") == "train"
    )
    eligible_evaluation = sum(
        1
        for item in observations
        if isinstance(item, Mapping) and item.get("eligible_for_teacher") is True and item.get("split") == "evaluation"
    )
    if _count(
        value.get("eligible_train_observation_count"),
        label="photoreal frame index eligible_train_observation_count",
    ) != eligible_train:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index eligible training count mismatch")
    if _count(
        value.get("eligible_evaluation_observation_count"),
        label="photoreal frame index eligible_evaluation_observation_count",
    ) != eligible_evaluation:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index eligible evaluation count mismatch")

    duplicates = value.get("cross_split_near_duplicates")
    if not isinstance(duplicates, list):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index near-duplicate evidence is invalid")
    if _count(
        value.get("cross_split_near_duplicate_count"),
        label="photoreal frame index cross_split_near_duplicate_count",
    ) != len(duplicates):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index near-duplicate count mismatch")

    blockers = value.get("training_blockers")
    if not isinstance(blockers, list) or not all(isinstance(item, str) and item for item in blockers):
        raise PhotorealFrameIndexIntegrityError("photoreal frame index training blockers are invalid")
    if value.get("teacher_training_authorized") is True and blockers:
        raise PhotorealFrameIndexIntegrityError("authorized photoreal frame index still has training blockers")
    if value.get("teacher_training_authorized") is False and not blockers:
        raise PhotorealFrameIndexIntegrityError("blocked photoreal frame index has no training blocker")

    expected = _sha(value.get(DIGEST_FIELD), label="photoreal frame index SHA-256")
    observed = canonical_frame_index_sha256(value)
    if observed != expected:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index canonical digest mismatch")
    return observed


def seal_frame_index(
    value: Mapping[str, Any],
    source_authorized_observations_sha256: str,
) -> dict[str, Any]:
    if DIGEST_FIELD in value or SOURCE_DIGEST_FIELD in value:
        raise PhotorealFrameIndexIntegrityError("photoreal frame index is already lineage-bound or sealed")
    result = dict(value)
    result[SOURCE_DIGEST_FIELD] = _sha(
        source_authorized_observations_sha256,
        label="source authorized observations SHA-256",
    )
    result[DIGEST_FIELD] = canonical_frame_index_sha256(result)
    validate_frame_index_integrity(result)
    return result
