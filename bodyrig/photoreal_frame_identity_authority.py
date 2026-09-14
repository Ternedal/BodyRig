from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
MEASUREMENTS_FORMAT = "bodyrig-photoreal-frame-observations"
MEASUREMENTS_VERSION = 1
BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
CALIBRATION_FORMAT = "bodyrig-photoreal-identity-calibration"
CALIBRATION_VERSION = 1
FORMAT = "bodyrig-photoreal-frame-authorized-observations"
VERSION = 1
SOURCE_AUTHORITY = "stash-single-performer-target-binding-v1"
CALIBRATED_AUTHORITY = "calibrated-identity-bank-v1"
UNRESOLVED_AUTHORITY = "identity-unresolved-v1"


class PhotorealFrameIdentityAuthorityError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIdentityAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIdentityAuthorityError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealFrameIdentityAuthorityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealFrameIdentityAuthorityError(f"{label} is invalid")
    return result


def _count(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealFrameIdentityAuthorityError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIdentityAuthorityError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealFrameIdentityAuthorityError(f"{label} cannot be negative")
    return result


def _embedding(value: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise PhotorealFrameIdentityAuthorityError(f"{label} dimension mismatch")
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise PhotorealFrameIdentityAuthorityError(f"{label} contains boolean")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise PhotorealFrameIdentityAuthorityError(f"{label} contains non-numeric value") from exc
        if not math.isfinite(number):
            raise PhotorealFrameIdentityAuthorityError(f"{label} contains non-finite value")
        vector.append(number)
    norm = math.sqrt(sum(number * number for number in vector))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise PhotorealFrameIdentityAuthorityError(f"{label} has zero/invalid norm")
    return [number / norm for number in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def _plan_sources(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealFrameIdentityAuthorityError("photoreal dataset plan format/version mismatch")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealFrameIdentityAuthorityError("photoreal dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False or plan.get("teacher_training_authorized") is not False:
        raise PhotorealFrameIdentityAuthorityError("photoreal dataset plan crossed downstream authority")
    result: dict[str, dict[str, Any]] = {}
    for split in ("train", "evaluation"):
        values = plan.get(split)
        if not isinstance(values, list) or not values:
            raise PhotorealFrameIdentityAuthorityError(f"dataset plan {split} sources are invalid")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise PhotorealFrameIdentityAuthorityError("dataset source is invalid")
            source_key = _text(raw.get("source_id"), label="dataset source key")
            if source_key in result:
                raise PhotorealFrameIdentityAuthorityError(f"dataset source repeats: {source_key}")
            result[source_key] = {
                "performer_count": _count(raw.get("performer_count"), label="dataset performer_count"),
                "source_binding": _text(raw.get("source_binding"), label="dataset source binding", maximum=128),
            }
    return result


def _source_authoritative(source: Mapping[str, Any]) -> bool:
    return int(source["performer_count"]) == 1 and source["source_binding"] in {
        "scene-performer",
        "direct-performer",
    }


def _validate_bank_and_calibration(
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> tuple[int, list[float], float | None, bool]:
    if bank.get("format") != BANK_FORMAT or bank.get("version") != BANK_VERSION:
        raise PhotorealFrameIdentityAuthorityError("identity bank format/version mismatch")
    if bank.get("train_only") is not True or bank.get("evaluation_reference_count") != 0:
        raise PhotorealFrameIdentityAuthorityError("identity bank is not train-only")
    if bank.get("build_only") is not True or bank.get("runtime_dependency") is not False:
        raise PhotorealFrameIdentityAuthorityError("identity bank authority boundary is invalid")
    if bank.get("production_activation") is not False:
        raise PhotorealFrameIdentityAuthorityError("identity bank crossed production authority")
    dimension = _count(bank.get("embedding_dimension"), label="identity embedding dimension")
    if not 32 <= dimension <= 4096:
        raise PhotorealFrameIdentityAuthorityError("identity embedding dimension is outside supported bounds")
    centroid = _embedding(bank.get("centroid_embedding"), dimension=dimension, label="identity bank centroid")
    bank_sha = _sha(bank.get("identity_bank_sha256"), label="identity bank SHA-256")
    model_sha = _sha(bank.get("model_set_sha256"), label="identity model-set SHA-256")

    if calibration.get("format") != CALIBRATION_FORMAT or calibration.get("version") != CALIBRATION_VERSION:
        raise PhotorealFrameIdentityAuthorityError("identity calibration format/version mismatch")
    if _sha(calibration.get("identity_bank_sha256"), label="calibration identity bank SHA-256") != bank_sha:
        raise PhotorealFrameIdentityAuthorityError("identity calibration targets different bank")
    if _sha(calibration.get("model_set_sha256"), label="calibration model-set SHA-256") != model_sha:
        raise PhotorealFrameIdentityAuthorityError("identity calibration targets different model set")
    if calibration.get("build_only") is not True or calibration.get("runtime_dependency") is not False:
        raise PhotorealFrameIdentityAuthorityError("identity calibration authority boundary is invalid")
    if calibration.get("teacher_training_authorized") is not False or calibration.get("photoreal_acceptance_authority") is not False:
        raise PhotorealFrameIdentityAuthorityError("identity calibration crossed downstream authority")
    if calibration.get("production_activation") is not False:
        raise PhotorealFrameIdentityAuthorityError("identity calibration crossed production authority")
    authorized = calibration.get("identity_matching_authorized") is True
    calibrated = calibration.get("match_threshold_calibrated") is True
    threshold_raw = calibration.get("match_threshold")
    if authorized != calibrated:
        raise PhotorealFrameIdentityAuthorityError("identity calibration matching/threshold authority is inconsistent")
    threshold: float | None
    if authorized:
        if isinstance(threshold_raw, bool):
            raise PhotorealFrameIdentityAuthorityError("identity match threshold is invalid")
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError) as exc:
            raise PhotorealFrameIdentityAuthorityError("identity match threshold is invalid") from exc
        if not math.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
            raise PhotorealFrameIdentityAuthorityError("identity match threshold is outside cosine range")
        if calibration.get("calibration_blockers") != []:
            raise PhotorealFrameIdentityAuthorityError("authorized identity calibration still has blockers")
    else:
        if threshold_raw is not None:
            raise PhotorealFrameIdentityAuthorityError("unauthorized identity calibration must not expose threshold")
        threshold = None
    return dimension, centroid, threshold, authorized


def authorize_frame_identities(
    plan: Mapping[str, Any],
    measurements: Mapping[str, Any],
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    sources = _plan_sources(plan)
    dimension, centroid, threshold, calibrated_matching = _validate_bank_and_calibration(bank, calibration)
    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if _text(bank.get("performer_id"), label="identity bank performer id", maximum=256) != performer_id:
        raise PhotorealFrameIdentityAuthorityError("dataset plan/identity bank performer mismatch")

    if measurements.get("format") != MEASUREMENTS_FORMAT or measurements.get("version") != MEASUREMENTS_VERSION:
        raise PhotorealFrameIdentityAuthorityError("photoreal frame measurements format/version mismatch")
    if str(measurements.get("performer_id") or "") != performer_id:
        raise PhotorealFrameIdentityAuthorityError("photoreal frame measurements performer mismatch")
    if measurements.get("build_only") is not True or measurements.get("production_activation") is not False:
        raise PhotorealFrameIdentityAuthorityError("photoreal frame measurements authority boundary is invalid")
    model_sha = _sha(measurements.get("analyzer_model_set_sha256"), label="frame analyzer model-set SHA-256")
    if model_sha != bank.get("model_set_sha256"):
        raise PhotorealFrameIdentityAuthorityError("frame analyzer identity measurements use different model set")
    measured_dimension = _count(measurements.get("identity_embedding_dimension"), label="frame identity embedding dimension")
    if measured_dimension != dimension:
        raise PhotorealFrameIdentityAuthorityError("frame analyzer identity embedding dimension differs from bank")
    analyzer = _text(measurements.get("analyzer"), label="frame analyzer", maximum=256)
    analyzer_revision = _text(measurements.get("analyzer_revision"), label="frame analyzer revision", maximum=256)

    values = measurements.get("observations")
    if not isinstance(values, list) or not values:
        raise PhotorealFrameIdentityAuthorityError("photoreal frame measurements are empty")
    authorized_observations: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealFrameIdentityAuthorityError("photoreal frame measurement is invalid")
        if "target_identity_verified" in raw or "identity_confidence" in raw:
            raise PhotorealFrameIdentityAuthorityError("external frame measurement attempted to assert identity authority")
        source_key = _text(raw.get("source_key"), label="frame source key")
        source = sources.get(source_key)
        if source is None:
            raise PhotorealFrameIdentityAuthorityError(f"frame measurement references unknown dataset source: {source_key}")
        status = _text(raw.get("identity_measurement_status"), label="identity measurement status", maximum=32)
        embedding_raw = raw.get("identity_embedding")
        similarity: float | None = None
        if status == "available":
            embedding = _embedding(embedding_raw, dimension=dimension, label="frame identity embedding")
            similarity = _cosine(embedding, centroid)
        elif status == "unavailable":
            if embedding_raw is not None:
                raise PhotorealFrameIdentityAuthorityError("unavailable identity measurement must have null embedding")
        else:
            raise PhotorealFrameIdentityAuthorityError("identity measurement status is unsupported")

        if _source_authoritative(source):
            target_verified = True
            authority = SOURCE_AUTHORITY
        elif calibrated_matching and similarity is not None and threshold is not None and similarity >= threshold:
            target_verified = True
            authority = CALIBRATED_AUTHORITY
        else:
            target_verified = False
            authority = UNRESOLVED_AUTHORITY

        item = {key: value for key, value in raw.items() if key not in {"identity_embedding", "identity_measurement_status"}}
        item.update(
            {
                "identity_measurement_status": status,
                "identity_similarity": None if similarity is None else round(similarity, 9),
                "target_identity_verified": target_verified,
                "identity_authority": authority,
            }
        )
        authorized_observations.append(item)

    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "analyzer": analyzer,
        "analyzer_revision": analyzer_revision,
        "analyzer_model_set_sha256": model_sha,
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "identity_calibration_sha256": _sha(
            calibration.get("identity_calibration_sha256"), label="identity calibration SHA-256"
        ),
        "identity_matching_calibrated": calibrated_matching,
        "identity_match_threshold": threshold,
        "observations": authorized_observations,
        "identity_authority_is_core_derived": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def authorize_frame_identity_files(
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
    result = authorize_frame_identities(plan, measurements, bank, calibration)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIdentityAuthorityError(f"frame identity authority output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
