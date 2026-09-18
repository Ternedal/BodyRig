from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

BOOTSTRAP_FORMAT = "bodyrig-photoreal-identity-bootstrap-plan"
BOOTSTRAP_VERSION = 1
MODEL_SET_FORMAT = "bodyrig-photoreal-analyzer-model-set"
MODEL_SET_VERSION = 1
OBSERVATIONS_FORMAT = "bodyrig-photoreal-identity-reference-observations"
OBSERVATIONS_VERSION = 1
FORMAT = "bodyrig-photoreal-identity-bank"
VERSION = 1
MIN_EMBEDDING_DIMENSION = 32
MAX_EMBEDDING_DIMENSION = 4096
MIN_REFERENCE_COUNT = 4
MIN_REFERENCE_GROUPS = 2


class PhotorealIdentityBankError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityBankError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityBankError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealIdentityBankError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityBankError(f"{label} is invalid")
    return result


def _embedding(value: Any, *, dimension: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealIdentityBankError("identity embedding dimension mismatch")
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise PhotorealIdentityBankError("identity embedding contains boolean")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise PhotorealIdentityBankError("identity embedding contains non-numeric value") from exc
        if not math.isfinite(number):
            raise PhotorealIdentityBankError("identity embedding contains non-finite value")
        vector.append(number)
    norm = math.sqrt(sum(number * number for number in vector))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealIdentityBankError("identity embedding has zero/invalid norm")
    return [number / norm for number in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def _normalized_mean(vectors: list[list[float]]) -> list[float]:
    dimension = len(vectors[0])
    mean = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(dimension)]
    norm = math.sqrt(sum(value * value for value in mean))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealIdentityBankError("identity reference centroid collapsed")
    return [value / norm for value in mean]


def _bootstrap_sources(bootstrap: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if bootstrap.get("format") != BOOTSTRAP_FORMAT or bootstrap.get("version") != BOOTSTRAP_VERSION:
        raise PhotorealIdentityBankError("identity bootstrap format/version mismatch")
    if bootstrap.get("train_only") is not True or bootstrap.get("evaluation_source_count") != 0:
        raise PhotorealIdentityBankError("identity bootstrap is not train-only")
    if bootstrap.get("source_bytes_bound") is not True or bootstrap.get("identity_bank_build_authorized") is not True:
        raise PhotorealIdentityBankError("identity bootstrap lacks source/bank authority")
    if bootstrap.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityBankError("identity bootstrap crossed teacher-training authority")
    if bootstrap.get("build_only") is not True or bootstrap.get("runtime_dependency") is not False:
        raise PhotorealIdentityBankError("identity bootstrap authority boundary is invalid")
    if bootstrap.get("production_activation") is not False:
        raise PhotorealIdentityBankError("identity bootstrap crossed production authority")

    values = bootstrap.get("sources")
    if not isinstance(values, list) or len(values) < 2:
        raise PhotorealIdentityBankError("identity bootstrap contains too few sources")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityBankError("identity bootstrap source is invalid")
        source_key = _text(raw.get("source_key"), label="bootstrap source key")
        if source_key in result:
            raise PhotorealIdentityBankError(f"identity bootstrap repeats source key: {source_key}")
        samples = raw.get("reference_samples")
        if not isinstance(samples, list) or not samples:
            raise PhotorealIdentityBankError("identity bootstrap source has no reference samples")
        allowed_samples: set[tuple[float | None, str]] = set()
        for sample in samples:
            if not isinstance(sample, Mapping):
                raise PhotorealIdentityBankError("identity bootstrap sample is invalid")
            timestamp = sample.get("timestamp_seconds")
            normalized_timestamp = None if timestamp is None else round(float(timestamp), 6)
            eye = _text(sample.get("eye"), label="bootstrap sample eye", maximum=16)
            allowed_samples.add((normalized_timestamp, eye))
        result[source_key] = {
            "source_sha256": _sha(raw.get("source_sha256"), label="bootstrap source SHA-256"),
            "group_id": _text(raw.get("group_id"), label="bootstrap group id"),
            "allowed_samples": allowed_samples,
        }
    return result


def _model_set_sha(model_set: Mapping[str, Any]) -> str:
    if model_set.get("format") != MODEL_SET_FORMAT or model_set.get("version") != MODEL_SET_VERSION:
        raise PhotorealIdentityBankError("identity model-set format/version mismatch")
    if model_set.get("build_only") is not True or model_set.get("runtime_dependency") is not False:
        raise PhotorealIdentityBankError("identity model-set authority boundary is invalid")
    if model_set.get("production_activation") is not False:
        raise PhotorealIdentityBankError("identity model-set crossed production authority")
    return _sha(model_set.get("model_set_sha256"), label="identity model-set SHA-256")


def _canonical_bank_digest(value: Mapping[str, Any]) -> str:
    payload = {
        "format": value["format"],
        "version": value["version"],
        "performer_id": value["performer_id"],
        "extractor": value["extractor"],
        "extractor_revision": value["extractor_revision"],
        "model_set_sha256": value["model_set_sha256"],
        "embedding_dimension": value["embedding_dimension"],
        "references": value["references"],
        "centroid_embedding": value["centroid_embedding"],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_identity_bank(
    bootstrap: Mapping[str, Any],
    model_set: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    bootstrap_sources = _bootstrap_sources(bootstrap)
    model_set_sha256 = _model_set_sha(model_set)
    performer_id = _text(bootstrap.get("performer_id"), label="performer id", maximum=256)

    if observations.get("format") != OBSERVATIONS_FORMAT or observations.get("version") != OBSERVATIONS_VERSION:
        raise PhotorealIdentityBankError("identity reference observations format/version mismatch")
    if _text(observations.get("performer_id"), label="observation performer id", maximum=256) != performer_id:
        raise PhotorealIdentityBankError("identity reference observations performer mismatch")
    if _sha(observations.get("model_set_sha256"), label="observation model-set SHA-256") != model_set_sha256:
        raise PhotorealIdentityBankError("identity reference observations target a different model set")
    if observations.get("build_only") is not True or observations.get("production_activation") is not False:
        raise PhotorealIdentityBankError("identity reference observations authority boundary is invalid")

    extractor = _text(observations.get("extractor"), label="identity extractor", maximum=256)
    extractor_revision = _text(
        observations.get("extractor_revision"), label="identity extractor revision", maximum=256
    )
    dimension_raw = observations.get("embedding_dimension")
    if isinstance(dimension_raw, bool):
        raise PhotorealIdentityBankError("identity embedding dimension is invalid")
    try:
        dimension = int(dimension_raw)
    except (TypeError, ValueError) as exc:
        raise PhotorealIdentityBankError("identity embedding dimension is invalid") from exc
    if not MIN_EMBEDDING_DIMENSION <= dimension <= MAX_EMBEDDING_DIMENSION:
        raise PhotorealIdentityBankError("identity embedding dimension is outside supported bounds")

    values = observations.get("observations")
    if not isinstance(values, list) or len(values) < MIN_REFERENCE_COUNT:
        raise PhotorealIdentityBankError(f"identity bank requires at least {MIN_REFERENCE_COUNT} reference observations")

    references: list[dict[str, Any]] = []
    vectors: list[list[float]] = []
    groups: set[str] = set()
    seen_frames: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityBankError("identity reference observation is invalid")
        source_key = _text(raw.get("source_key"), label="identity reference source key")
        source = bootstrap_sources.get(source_key)
        if source is None:
            raise PhotorealIdentityBankError(f"identity reference uses non-authoritative source: {source_key}")
        source_sha = _sha(raw.get("source_sha256"), label="identity reference source SHA-256")
        if source_sha != source["source_sha256"]:
            raise PhotorealIdentityBankError(f"identity reference source bytes changed: {source_key}")
        eye = _text(raw.get("eye"), label="identity reference eye", maximum=16)
        timestamp_raw = raw.get("timestamp_seconds")
        timestamp = None if timestamp_raw is None else round(float(timestamp_raw), 6)
        if (timestamp, eye) not in source["allowed_samples"]:
            raise PhotorealIdentityBankError(f"identity reference was not authorized by bootstrap plan: {source_key}")
        frame_sha = _sha(raw.get("frame_sha256"), label="identity reference frame SHA-256")
        if frame_sha in seen_frames:
            raise PhotorealIdentityBankError("identity reference frame is duplicated")
        seen_frames.add(frame_sha)
        vector = _embedding(raw.get("embedding"), dimension=dimension)
        vectors.append(vector)
        groups.add(source["group_id"])
        references.append(
            {
                "source_key": source_key,
                "source_sha256": source_sha,
                "group_id": source["group_id"],
                "timestamp_seconds": timestamp,
                "eye": eye,
                "frame_sha256": frame_sha,
                "embedding": [round(number, 9) for number in vector],
            }
        )

    if len(groups) < MIN_REFERENCE_GROUPS:
        raise PhotorealIdentityBankError(
            f"identity bank requires references from at least {MIN_REFERENCE_GROUPS} independent train groups"
        )

    references.sort(
        key=lambda item: (
            item["group_id"],
            item["source_key"],
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            item["eye"],
            item["frame_sha256"],
        )
    )
    ordered_vectors = [list(item["embedding"]) for item in references]
    centroid = _normalized_mean(ordered_vectors)
    similarities = [_cosine(vector, centroid) for vector in ordered_vectors]

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": str(bootstrap.get("performer_name") or ""),
        "extractor": extractor,
        "extractor_revision": extractor_revision,
        "model_set_sha256": model_set_sha256,
        "embedding_dimension": dimension,
        "reference_count": len(references),
        "source_group_count": len(groups),
        "references": references,
        "centroid_embedding": [round(number, 9) for number in centroid],
        "reference_to_centroid_cosine_min": round(min(similarities), 9),
        "reference_to_centroid_cosine_median": round(statistics.median(similarities), 9),
        "reference_to_centroid_cosine_max": round(max(similarities), 9),
        "train_only": True,
        "evaluation_reference_count": 0,
        "match_threshold_calibrated": False,
        "identity_matching_authorized": False,
        "identity_bank_ready_for_calibration": True,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["identity_bank_sha256"] = _canonical_bank_digest(result)
    return result


def build_identity_bank_files(
    bootstrap_path: str | Path,
    model_set_path: str | Path,
    observations_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    bootstrap = _read_json(bootstrap_path, label="identity bootstrap plan")
    model_set = _read_json(model_set_path, label="identity model set")
    observations = _read_json(observations_path, label="identity reference observations")
    result = build_identity_bank(bootstrap, model_set, observations)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityBankError(f"identity bank output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
