from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
PLAN_FORMAT = "bodyrig-photoreal-identity-calibration-plan"
PLAN_VERSION = 1
OBSERVATIONS_FORMAT = "bodyrig-photoreal-identity-negative-observations"
OBSERVATIONS_VERSION = 1
FORMAT = "bodyrig-photoreal-identity-calibration"
VERSION = 1
MIN_NEGATIVE_OBSERVATIONS = 8
MIN_NEGATIVE_PERFORMERS = 2
MIN_COSINE_SEPARATION_MARGIN = 0.05
THRESHOLD_DERIVATION = "midpoint-positive-floor-negative-ceiling-v1"


class PhotorealIdentityCalibrationError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealIdentityCalibrationError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationError(f"{label} is invalid")
    return result


def _embedding(value: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealIdentityCalibrationError(f"{label} dimension mismatch")
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise PhotorealIdentityCalibrationError(f"{label} contains boolean")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise PhotorealIdentityCalibrationError(f"{label} contains non-numeric value") from exc
        if not math.isfinite(number):
            raise PhotorealIdentityCalibrationError(f"{label} contains non-finite value")
        vector.append(number)
    norm = math.sqrt(sum(number * number for number in vector))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealIdentityCalibrationError(f"{label} has zero/invalid norm")
    return [number / norm for number in vector]


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise PhotorealIdentityCalibrationError("cannot build identity centroid from zero vectors")
    dimension = len(vectors[0])
    mean = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(dimension)]
    norm = math.sqrt(sum(value * value for value in mean))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealIdentityCalibrationError("identity centroid collapsed")
    return [value / norm for value in mean]


def _cosine(left: list[float], right: list[float]) -> float:
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def _canonical_bank_digest(bank: Mapping[str, Any]) -> str:
    required = [
        "format",
        "version",
        "performer_id",
        "extractor",
        "extractor_revision",
        "model_set_sha256",
        "embedding_dimension",
        "references",
        "centroid_embedding",
    ]
    payload = {key: bank.get(key) for key in required}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _canonical_calibration_digest(value: Mapping[str, Any]) -> str:
    keys = [
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
    ]
    raw = json.dumps(
        {key: value.get(key) for key in keys},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_bank(bank: Mapping[str, Any]) -> tuple[int, list[dict[str, Any]], list[float]]:
    if bank.get("format") != BANK_FORMAT or bank.get("version") != BANK_VERSION:
        raise PhotorealIdentityCalibrationError("identity bank format/version mismatch")
    if bank.get("train_only") is not True or bank.get("evaluation_reference_count") != 0:
        raise PhotorealIdentityCalibrationError("identity bank is not train-only")
    if bank.get("match_threshold_calibrated") is not False or bank.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationError("identity bank is already calibrated/authorized")
    if bank.get("identity_bank_ready_for_calibration") is not True:
        raise PhotorealIdentityCalibrationError("identity bank is not ready for calibration")
    if bank.get("teacher_training_authorized") is not False or bank.get("photoreal_acceptance_authority") is not False:
        raise PhotorealIdentityCalibrationError("identity bank crossed downstream authority")
    if bank.get("build_only") is not True or bank.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationError("identity bank authority boundary is invalid")
    if bank.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationError("identity bank crossed production authority")
    expected_digest = _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256")
    if _canonical_bank_digest(bank) != expected_digest:
        raise PhotorealIdentityCalibrationError("identity bank canonical digest mismatch")
    dimension_raw = bank.get("embedding_dimension")
    if isinstance(dimension_raw, bool):
        raise PhotorealIdentityCalibrationError("identity bank embedding dimension is invalid")
    try:
        dimension = int(dimension_raw)
    except (TypeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationError("identity bank embedding dimension is invalid") from exc
    if not 32 <= dimension <= 4096:
        raise PhotorealIdentityCalibrationError("identity bank embedding dimension is outside supported bounds")
    references_raw = bank.get("references")
    if not isinstance(references_raw, list) or len(references_raw) < 4:
        raise PhotorealIdentityCalibrationError("identity bank has too few positive references")
    references: list[dict[str, Any]] = []
    groups: set[str] = set()
    for raw in references_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCalibrationError("identity bank reference is invalid")
        group_id = _text(raw.get("group_id"), label="identity bank reference group")
        vector = _embedding(raw.get("embedding"), dimension=dimension, label="identity bank reference embedding")
        groups.add(group_id)
        references.append({"group_id": group_id, "embedding": vector})
    if len(groups) < 2:
        raise PhotorealIdentityCalibrationError("identity bank requires at least two positive source groups")
    bank_centroid = _embedding(
        bank.get("centroid_embedding"),
        dimension=dimension,
        label="identity bank centroid embedding",
    )
    rebuilt = _centroid([item["embedding"] for item in references])
    if _cosine(bank_centroid, rebuilt) < 0.999999:
        raise PhotorealIdentityCalibrationError("identity bank centroid is inconsistent with references")
    return dimension, references, bank_centroid


def _validate_plan(plan: Mapping[str, Any], bank: Mapping[str, Any], dimension: int) -> dict[str, dict[str, Any]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealIdentityCalibrationError("identity calibration plan format/version mismatch")
    if plan.get("calibration_only") is not True or plan.get("negative_embedding_extraction_required") is not True:
        raise PhotorealIdentityCalibrationError("identity calibration plan authority is invalid")
    if plan.get("teacher_training_authorized") is not False or plan.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationError("identity calibration plan crossed matching/training authority")
    if plan.get("photoreal_acceptance_authority") is not False:
        raise PhotorealIdentityCalibrationError("identity calibration plan crossed photoreal authority")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationError("identity calibration plan build/runtime authority is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationError("identity calibration plan crossed production authority")
    if _text(plan.get("target_performer_id"), label="calibration target performer", maximum=256) != _text(
        bank.get("performer_id"), label="bank performer id", maximum=256
    ):
        raise PhotorealIdentityCalibrationError("identity calibration plan/bank performer mismatch")
    if _sha(plan.get("identity_bank_sha256"), label="plan identity bank SHA-256") != bank["identity_bank_sha256"]:
        raise PhotorealIdentityCalibrationError("identity calibration plan targets different bank")
    if _sha(plan.get("model_set_sha256"), label="plan model-set SHA-256") != bank["model_set_sha256"]:
        raise PhotorealIdentityCalibrationError("identity calibration plan targets different model set")
    if plan.get("extractor") != bank.get("extractor") or plan.get("extractor_revision") != bank.get("extractor_revision"):
        raise PhotorealIdentityCalibrationError("identity calibration plan/bank extractor provenance mismatch")
    if int(plan.get("embedding_dimension")) != dimension:
        raise PhotorealIdentityCalibrationError("identity calibration plan embedding dimension mismatch")
    values = plan.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealIdentityCalibrationError("identity calibration plan contains no negative sources")
    sources: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCalibrationError("identity calibration source is invalid")
        source_key = _text(raw.get("source_key"), label="calibration source key")
        if source_key in sources:
            raise PhotorealIdentityCalibrationError(f"identity calibration source is duplicated: {source_key}")
        subject = _text(raw.get("subject_performer_id"), label="calibration negative subject", maximum=256)
        if subject == bank.get("performer_id") or raw.get("target_performer_absent") is not True:
            raise PhotorealIdentityCalibrationError("calibration negative source can contain target performer")
        samples_raw = raw.get("samples")
        if not isinstance(samples_raw, list) or not samples_raw:
            raise PhotorealIdentityCalibrationError("calibration negative source has no samples")
        samples: set[tuple[float | None, str]] = set()
        for sample in samples_raw:
            if not isinstance(sample, Mapping):
                raise PhotorealIdentityCalibrationError("calibration negative sample is invalid")
            timestamp_raw = sample.get("timestamp_seconds")
            timestamp = None if timestamp_raw is None else round(float(timestamp_raw), 6)
            eye = _text(sample.get("eye"), label="calibration negative eye", maximum=16)
            samples.add((timestamp, eye))
        sources[source_key] = {
            "source_sha256": _sha(raw.get("source_sha256"), label="calibration source SHA-256"),
            "subject_performer_id": subject,
            "samples": samples,
        }
    return sources


def build_identity_calibration(
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
) -> dict[str, Any]:
    dimension, positive_references, bank_centroid = _validate_bank(bank)
    plan_sources = _validate_plan(plan, bank, dimension)
    if negative_observations.get("format") != OBSERVATIONS_FORMAT or negative_observations.get("version") != OBSERVATIONS_VERSION:
        raise PhotorealIdentityCalibrationError("identity negative observations format/version mismatch")
    if str(negative_observations.get("target_performer_id") or "") != str(bank.get("performer_id") or ""):
        raise PhotorealIdentityCalibrationError("identity negative observations target performer mismatch")
    if _sha(negative_observations.get("identity_bank_sha256"), label="negative observations bank SHA-256") != bank["identity_bank_sha256"]:
        raise PhotorealIdentityCalibrationError("identity negative observations target different bank")
    if negative_observations.get("extractor") != bank.get("extractor") or negative_observations.get("extractor_revision") != bank.get("extractor_revision"):
        raise PhotorealIdentityCalibrationError("identity negative observations extractor provenance mismatch")
    if _sha(negative_observations.get("model_set_sha256"), label="negative observations model-set SHA-256") != bank["model_set_sha256"]:
        raise PhotorealIdentityCalibrationError("identity negative observations target different model set")
    if negative_observations.get("embedding_dimension") != dimension:
        raise PhotorealIdentityCalibrationError("identity negative observations embedding dimension mismatch")
    if negative_observations.get("calibration_only") is not True or negative_observations.get("build_only") is not True:
        raise PhotorealIdentityCalibrationError("identity negative observations crossed calibration/build authority")
    if negative_observations.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationError("identity negative observations crossed production authority")

    raw_negatives = negative_observations.get("observations")
    if not isinstance(raw_negatives, list) or not raw_negatives:
        raise PhotorealIdentityCalibrationError("identity negative observations are empty")
    negative_vectors: list[tuple[str, list[float]]] = []
    seen_frames: set[str] = set()
    for raw in raw_negatives:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCalibrationError("identity negative observation is invalid")
        source_key = _text(raw.get("source_key"), label="negative observation source key")
        source = plan_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityCalibrationError(f"identity negative observation uses unplanned source: {source_key}")
        if _sha(raw.get("source_sha256"), label="negative observation source SHA-256") != source["source_sha256"]:
            raise PhotorealIdentityCalibrationError(f"identity negative observation source bytes changed: {source_key}")
        subject = _text(raw.get("subject_performer_id"), label="negative observation subject", maximum=256)
        if subject != source["subject_performer_id"]:
            raise PhotorealIdentityCalibrationError("identity negative observation subject label changed")
        timestamp_raw = raw.get("timestamp_seconds")
        timestamp = None if timestamp_raw is None else round(float(timestamp_raw), 6)
        eye = _text(raw.get("eye"), label="negative observation eye", maximum=16)
        if (timestamp, eye) not in source["samples"]:
            raise PhotorealIdentityCalibrationError(f"identity negative observation sample was not planned: {source_key}")
        frame_sha = _sha(raw.get("frame_sha256"), label="negative observation frame SHA-256")
        if frame_sha in seen_frames:
            raise PhotorealIdentityCalibrationError("identity negative observation frame is duplicated")
        seen_frames.add(frame_sha)
        vector = _embedding(raw.get("embedding"), dimension=dimension, label="negative identity embedding")
        negative_vectors.append((subject, vector))

    positive_scores: list[float] = []
    for reference in positive_references:
        others = [
            item["embedding"]
            for item in positive_references
            if item["group_id"] != reference["group_id"]
        ]
        if not others:
            raise PhotorealIdentityCalibrationError("leave-group-out positive calibration has no independent group")
        positive_scores.append(_cosine(reference["embedding"], _centroid(others)))

    negative_scores = [_cosine(vector, bank_centroid) for _, vector in negative_vectors]
    positive_floor = min(positive_scores)
    negative_ceiling = max(negative_scores)
    observed_margin = positive_floor - negative_ceiling
    negative_subjects = {subject for subject, _ in negative_vectors}

    blockers: list[str] = []
    if len(negative_vectors) < MIN_NEGATIVE_OBSERVATIONS:
        blockers.append(f"requires at least {MIN_NEGATIVE_OBSERVATIONS} negative observations")
    if len(negative_subjects) < MIN_NEGATIVE_PERFORMERS:
        blockers.append(f"requires at least {MIN_NEGATIVE_PERFORMERS} distinct negative performers")
    if observed_margin < MIN_COSINE_SEPARATION_MARGIN:
        blockers.append(
            f"observed positive/negative cosine separation {observed_margin:.6f} is below required {MIN_COSINE_SEPARATION_MARGIN:.6f}"
        )

    authorized = not blockers
    threshold = (positive_floor + negative_ceiling) / 2.0 if authorized else None
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": str(bank.get("performer_id")),
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "model_set_sha256": bank["model_set_sha256"],
        "extractor": bank["extractor"],
        "extractor_revision": bank["extractor_revision"],
        "embedding_dimension": dimension,
        "positive_reference_count": len(positive_references),
        "positive_group_count": len({item["group_id"] for item in positive_references}),
        "negative_observation_count": len(negative_vectors),
        "negative_performer_count": len(negative_subjects),
        "positive_leave_group_out_cosine_min": round(positive_floor, 9),
        "positive_leave_group_out_cosine_median": round(statistics.median(positive_scores), 9),
        "positive_leave_group_out_cosine_max": round(max(positive_scores), 9),
        "negative_to_target_centroid_cosine_min": round(min(negative_scores), 9),
        "negative_to_target_centroid_cosine_median": round(statistics.median(negative_scores), 9),
        "negative_to_target_centroid_cosine_max": round(negative_ceiling, 9),
        "minimum_required_separation_margin": MIN_COSINE_SEPARATION_MARGIN,
        "observed_separation_margin": round(observed_margin, 9),
        "threshold_derivation": THRESHOLD_DERIVATION,
        "match_threshold": None if threshold is None else round(threshold, 9),
        "match_threshold_calibrated": authorized,
        "identity_matching_authorized": authorized,
        "calibration_blockers": blockers,
        "calibration_data_teacher_input": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["identity_calibration_sha256"] = _canonical_calibration_digest(result)
    return result


def build_identity_calibration_files(
    bank_path: str | Path,
    plan_path: str | Path,
    negative_observations_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    bank = _read_json(bank_path, label="identity bank")
    plan = _read_json(plan_path, label="identity calibration plan")
    observations = _read_json(negative_observations_path, label="identity negative observations")
    result = build_identity_calibration(bank, plan, observations)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationError(f"identity calibration output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
