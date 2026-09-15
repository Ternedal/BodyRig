from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

SCAN_FORMAT = "bodyrig-photoreal-scan-plan"
SCAN_VERSION = 1
FORMAT = "bodyrig-photoreal-identity-bootstrap-plan"
VERSION = 1
POLICY = "train-only-single-performer-direct-binding-v1"
MAX_REFERENCE_SAMPLES_PER_SOURCE = 12
MIN_BOOTSTRAP_GROUPS = 2
MIN_BOOTSTRAP_SOURCES = 2
MIN_BOOTSTRAP_REFERENCE_SAMPLES = 4
IDENTITY_BOOTSTRAP_DECODE_MODES = {"image-direct", "rectilinear-mono", "rectilinear-stereo-split"}


class PhotorealIdentityBootstrapError(ValueError):
    pass


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityBootstrapError(f"photoreal scan plan is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityBootstrapError("photoreal scan plan must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealIdentityBootstrapError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityBootstrapError(f"{label} is invalid")
    return result


def _count(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealIdentityBootstrapError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealIdentityBootstrapError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealIdentityBootstrapError(f"{label} cannot be negative")
    return result


def _authoritative_source(source: Mapping[str, Any]) -> bool:
    if source.get("split") != "train" or _count(source.get("performer_count"), label="performer_count") != 1:
        return False
    if source.get("decode_mode") not in IDENTITY_BOOTSTRAP_DECODE_MODES:
        return False
    kind = source.get("kind")
    binding = source.get("source_binding")
    if kind == "video":
        return binding == "scene-performer"
    if kind == "image":
        return binding == "direct-performer"
    return False


def _take_evenly(values: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(values) <= limit:
        return [dict(item) for item in values]
    selected: list[dict[str, Any]] = []
    used: set[int] = set()
    for index in range(limit):
        position = min(len(values) - 1, int((index + 0.5) * len(values) / limit))
        if position in used:
            continue
        used.add(position)
        selected.append(dict(values[position]))
    if len(selected) != limit:
        for position, item in enumerate(values):
            if position not in used:
                selected.append(dict(item))
                used.add(position)
            if len(selected) == limit:
                break
    return selected


def _select_reference_samples(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = source.get("samples")
    if not isinstance(raw, list) or not raw:
        raise PhotorealIdentityBootstrapError("identity bootstrap source has no scout samples")
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PhotorealIdentityBootstrapError("identity bootstrap sample is invalid")
        eye = _text(item.get("eye"), label="sample eye", maximum=16)
        if eye not in {"mono", "left", "right"}:
            raise PhotorealIdentityBootstrapError(f"identity bootstrap sample eye is unsupported: {eye}")
        timestamp = item.get("timestamp_seconds")
        if source.get("kind") == "image":
            if timestamp is not None or eye != "mono":
                raise PhotorealIdentityBootstrapError("identity bootstrap image sample must be mono with null timestamp")
        else:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
                raise PhotorealIdentityBootstrapError("identity bootstrap video sample timestamp is invalid")
            timestamp = round(float(timestamp), 6)
        normalized.append({"timestamp_seconds": timestamp, "eye": eye})

    if source.get("kind") == "image":
        return [normalized[0]]

    by_eye: dict[str, list[dict[str, Any]]] = {}
    for item in normalized:
        by_eye.setdefault(item["eye"], []).append(item)
    eyes = sorted(by_eye)
    if len(eyes) == 1:
        return _take_evenly(by_eye[eyes[0]], MAX_REFERENCE_SAMPLES_PER_SOURCE)

    per_eye = max(1, MAX_REFERENCE_SAMPLES_PER_SOURCE // len(eyes))
    selected: list[dict[str, Any]] = []
    for eye in eyes:
        selected.extend(_take_evenly(by_eye[eye], per_eye))
    selected.sort(key=lambda item: (float(item["timestamp_seconds"] or -1.0), item["eye"]))
    return selected[:MAX_REFERENCE_SAMPLES_PER_SOURCE]


def build_identity_bootstrap_plan(scan_plan: Mapping[str, Any]) -> dict[str, Any]:
    if scan_plan.get("format") != SCAN_FORMAT or scan_plan.get("version") != SCAN_VERSION:
        raise PhotorealIdentityBootstrapError("photoreal scan plan format/version mismatch")
    if scan_plan.get("identity_bootstrap_policy") != POLICY:
        raise PhotorealIdentityBootstrapError("photoreal scan plan identity bootstrap policy mismatch")
    if scan_plan.get("all_sources_sha256_bound") is not True:
        raise PhotorealIdentityBootstrapError("photoreal scan plan is not source-byte-bound")
    if scan_plan.get("train_evaluation_assignment_inherited") is not True:
        raise PhotorealIdentityBootstrapError("photoreal scan plan lost train/evaluation assignment")
    if scan_plan.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityBootstrapError("identity bootstrap requires a pre-training scan plan")
    if scan_plan.get("build_only") is not True or scan_plan.get("runtime_dependency") is not False:
        raise PhotorealIdentityBootstrapError("photoreal scan plan authority boundary is invalid")
    if scan_plan.get("production_activation") is not False:
        raise PhotorealIdentityBootstrapError("photoreal scan plan crossed production authority")

    values = scan_plan.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealIdentityBootstrapError("photoreal scan plan contains no sources")

    selected_sources: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityBootstrapError("photoreal scan source is invalid")
        source_key = _text(raw.get("source_key"), label="source key")
        if source_key in seen_keys:
            raise PhotorealIdentityBootstrapError(f"photoreal scan plan repeats source key: {source_key}")
        seen_keys.add(source_key)

        authoritative = _authoritative_source(raw)
        flagged = raw.get("identity_bootstrap_eligible")
        if not isinstance(flagged, bool) or flagged != authoritative:
            raise PhotorealIdentityBootstrapError(
                f"identity bootstrap eligibility disagrees with source authority: {source_key}"
            )
        if not authoritative:
            continue

        references = _select_reference_samples(raw)
        selected_sources.append(
            {
                "source_key": source_key,
                "source_sha256": _sha(raw.get("source_sha256"), label="source SHA-256"),
                "resolved_path": _text(raw.get("resolved_path"), label="resolved source path"),
                "kind": _text(raw.get("kind"), label="source kind", maximum=16),
                "group_id": _text(raw.get("group_id"), label="source group"),
                "source_binding": _text(raw.get("source_binding"), label="source binding", maximum=128),
                "performer_count": _count(raw.get("performer_count"), label="performer_count"),
                "projection": _text(raw.get("projection"), label="projection", maximum=128),
                "stereo_layout": _text(raw.get("stereo_layout"), label="stereo layout", maximum=128),
                "decode_mode": _text(raw.get("decode_mode"), label="decode mode", maximum=128),
                "reference_sample_count": len(references),
                "reference_samples": references,
            }
        )

    selected_sources.sort(key=lambda item: (item["group_id"], item["source_key"]))
    groups = {item["group_id"] for item in selected_sources}
    reference_count = sum(int(item["reference_sample_count"]) for item in selected_sources)
    blockers: list[str] = []
    if len(selected_sources) < MIN_BOOTSTRAP_SOURCES:
        blockers.append(f"requires at least {MIN_BOOTSTRAP_SOURCES} authoritative train sources")
    if len(groups) < MIN_BOOTSTRAP_GROUPS:
        blockers.append(f"requires at least {MIN_BOOTSTRAP_GROUPS} independent authoritative train groups")
    if reference_count < MIN_BOOTSTRAP_REFERENCE_SAMPLES:
        blockers.append(f"requires at least {MIN_BOOTSTRAP_REFERENCE_SAMPLES} identity reference samples")
    if blockers:
        raise PhotorealIdentityBootstrapError("; ".join(blockers))

    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(scan_plan.get("performer_id"), label="performer id", maximum=256),
        "performer_name": str(scan_plan.get("performer_name") or ""),
        "policy": POLICY,
        "source_count": len(selected_sources),
        "source_group_count": len(groups),
        "reference_sample_count": reference_count,
        "maximum_reference_samples_per_source": MAX_REFERENCE_SAMPLES_PER_SOURCE,
        "sources": selected_sources,
        "train_only": True,
        "evaluation_source_count": 0,
        "source_bytes_bound": True,
        "identity_embedding_extraction_required": True,
        "identity_bank_build_authorized": True,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_identity_bootstrap_plan_file(scan_plan_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    scan_plan = _read_json(scan_plan_path)
    result = build_identity_bootstrap_plan(scan_plan)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityBootstrapError(f"identity bootstrap output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
