from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

NEGATIVE_RECEIPT_FORMAT = "bodyrig-photoreal-identity-negative-receipt"
NEGATIVE_RECEIPT_VERSION = 1
BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
FORMAT = "bodyrig-photoreal-identity-calibration-plan"
VERSION = 1
LABEL_AUTHORITY = "stash-single-performer-other-id-v1"
VIDEO_TIMESTAMPS_PER_SOURCE = 6
MIN_NEGATIVE_PERFORMERS = 2
MIN_NEGATIVE_SOURCES = 2


class PhotorealIdentityCalibrationPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityCalibrationPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealIdentityCalibrationPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationPlanError(f"{label} is invalid")
    return result


def _positive(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise PhotorealIdentityCalibrationPlanError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationPlanError(f"{label} is invalid") from exc
    if not math.isfinite(result) or result <= 0:
        raise PhotorealIdentityCalibrationPlanError(f"{label} must be finite and positive")
    return result


def _eyes(stereo_layout: str) -> list[str]:
    if stereo_layout == "mono":
        return ["mono"]
    if stereo_layout in {"side-by-side", "over-under"}:
        return ["left", "right"]
    raise PhotorealIdentityCalibrationPlanError(
        f"negative calibration stereo layout is not decode-authoritative: {stereo_layout}"
    )


def _decode_mode(projection: str, stereo_layout: str) -> str:
    if projection == "flat" and stereo_layout == "mono":
        return "rectilinear-mono"
    if projection == "flat" and stereo_layout in {"side-by-side", "over-under"}:
        return "rectilinear-stereo-split"
    if projection in {"vr180", "vr360", "equirectangular"} and stereo_layout in {
        "mono",
        "side-by-side",
        "over-under",
    }:
        return "spatial-deprojection-required"
    raise PhotorealIdentityCalibrationPlanError(
        f"negative calibration projection/layout is not decode-authoritative: {projection}/{stereo_layout}"
    )


def _video_samples(duration: float, stereo_layout: str) -> list[dict[str, Any]]:
    timestamps = [round(duration * (index + 0.5) / VIDEO_TIMESTAMPS_PER_SOURCE, 6) for index in range(VIDEO_TIMESTAMPS_PER_SOURCE)]
    return [
        {"timestamp_seconds": timestamp, "eye": eye}
        for timestamp in timestamps
        for eye in _eyes(stereo_layout)
    ]


def build_identity_calibration_plan(
    identity_bank: Mapping[str, Any],
    negative_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if identity_bank.get("format") != BANK_FORMAT or identity_bank.get("version") != BANK_VERSION:
        raise PhotorealIdentityCalibrationPlanError("identity bank format/version mismatch")
    if identity_bank.get("train_only") is not True or identity_bank.get("evaluation_reference_count") != 0:
        raise PhotorealIdentityCalibrationPlanError("identity bank is not train-only")
    if identity_bank.get("match_threshold_calibrated") is not False or identity_bank.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity bank is already calibrated/authorized")
    if identity_bank.get("identity_bank_ready_for_calibration") is not True:
        raise PhotorealIdentityCalibrationPlanError("identity bank is not ready for calibration")
    if identity_bank.get("build_only") is not True or identity_bank.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity bank authority boundary is invalid")
    if identity_bank.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity bank crossed production authority")

    if negative_receipt.get("format") != NEGATIVE_RECEIPT_FORMAT or negative_receipt.get("version") != NEGATIVE_RECEIPT_VERSION:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt format/version mismatch")
    if negative_receipt.get("label_authority") != LABEL_AUTHORITY:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt label authority mismatch")
    if negative_receipt.get("all_sources_readable") is not True or negative_receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt is not byte-bound")
    if negative_receipt.get("calibration_only") is not True or negative_receipt.get("photoreal_teacher_input") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt crossed calibration/teacher boundary")
    if negative_receipt.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt crossed matching authority")
    if negative_receipt.get("build_only") is not True or negative_receipt.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt authority boundary is invalid")
    if negative_receipt.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationPlanError("identity negative receipt crossed production authority")
    negative_inventory_sha256 = _sha(
        negative_receipt.get("negative_inventory_sha256"),
        label="identity negative inventory SHA-256",
    )

    target = _text(identity_bank.get("performer_id"), label="identity bank performer id", maximum=256)
    if _text(negative_receipt.get("target_performer_id"), label="negative target performer id", maximum=256) != target:
        raise PhotorealIdentityCalibrationPlanError("identity bank/negative receipt target performer mismatch")

    values = negative_receipt.get("sources")
    if not isinstance(values, list) or len(values) < MIN_NEGATIVE_SOURCES:
        raise PhotorealIdentityCalibrationPlanError(
            f"identity calibration requires at least {MIN_NEGATIVE_SOURCES} verified negative sources"
        )
    subjects = {str(item.get("subject_performer_id") or "") for item in values if isinstance(item, Mapping)}
    subjects.discard("")
    if len(subjects) < MIN_NEGATIVE_PERFORMERS:
        raise PhotorealIdentityCalibrationPlanError(
            f"identity calibration requires at least {MIN_NEGATIVE_PERFORMERS} distinct negative performers"
        )

    sources: list[dict[str, Any]] = []
    total_samples = 0
    seen_keys: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityCalibrationPlanError("identity negative source is invalid")
        source_key = _text(raw.get("source_key"), label="negative source key")
        if source_key in seen_keys:
            raise PhotorealIdentityCalibrationPlanError(f"identity negative source key is duplicated: {source_key}")
        seen_keys.add(source_key)
        subject = _text(raw.get("subject_performer_id"), label="negative subject performer id", maximum=256)
        if subject == target or raw.get("target_performer_absent") is not True:
            raise PhotorealIdentityCalibrationPlanError("identity calibration negative source can contain target performer")
        if raw.get("label_authority") != LABEL_AUTHORITY:
            raise PhotorealIdentityCalibrationPlanError("identity calibration negative source label authority mismatch")
        kind = _text(raw.get("kind"), label="negative source kind", maximum=16)
        if kind == "image":
            projection = "flat"
            stereo_layout = "mono"
            decode_mode = "image-direct"
            samples = [{"timestamp_seconds": None, "eye": "mono"}]
        elif kind == "video":
            projection = _text(raw.get("projection"), label="negative projection", maximum=128)
            stereo_layout = _text(raw.get("stereo_layout"), label="negative stereo layout", maximum=128)
            decode_mode = _decode_mode(projection, stereo_layout)
            samples = _video_samples(
                _positive(raw.get("duration_seconds"), label="negative video duration"),
                stereo_layout,
            )
        else:
            raise PhotorealIdentityCalibrationPlanError(f"unsupported identity negative source kind: {kind}")
        total_samples += len(samples)
        sources.append(
            {
                "source_key": source_key,
                "source_sha256": _sha(raw.get("sha256"), label="negative source SHA-256"),
                "resolved_path": _text(raw.get("resolved_path"), label="negative resolved path"),
                "subject_performer_id": subject,
                "subject_performer_name": str(raw.get("subject_performer_name") or ""),
                "target_performer_id": target,
                "target_performer_absent": True,
                "label_authority": LABEL_AUTHORITY,
                "kind": kind,
                "source_binding": _text(raw.get("source_binding"), label="negative source binding", maximum=128),
                "projection": projection,
                "stereo_layout": stereo_layout,
                "decode_mode": decode_mode,
                "sample_count": len(samples),
                "samples": samples,
            }
        )

    sources.sort(key=lambda item: (item["subject_performer_id"], item["source_key"]))
    return {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": target,
        "identity_bank_sha256": _sha(identity_bank.get("identity_bank_sha256"), label="identity bank SHA-256"),
        "negative_inventory_sha256": negative_inventory_sha256,
        "model_set_sha256": _sha(identity_bank.get("model_set_sha256"), label="identity model-set SHA-256"),
        "extractor": _text(identity_bank.get("extractor"), label="identity extractor", maximum=256),
        "extractor_revision": _text(
            identity_bank.get("extractor_revision"), label="identity extractor revision", maximum=256
        ),
        "embedding_dimension": int(identity_bank.get("embedding_dimension")),
        "label_authority": LABEL_AUTHORITY,
        "negative_performer_count": len(subjects),
        "source_count": len(sources),
        "planned_negative_observation_count": total_samples,
        "video_timestamps_per_source": VIDEO_TIMESTAMPS_PER_SOURCE,
        "sources": sources,
        "negative_embedding_extraction_required": True,
        "calibration_only": True,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_identity_calibration_plan_files(
    identity_bank_path: str | Path,
    negative_receipt_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    bank = _read_json(identity_bank_path, label="identity bank")
    receipt = _read_json(negative_receipt_path, label="identity negative receipt")
    result = build_identity_calibration_plan(bank, receipt)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationPlanError(f"identity calibration plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
