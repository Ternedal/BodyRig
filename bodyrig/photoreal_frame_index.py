from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
OBSERVATIONS_FORMAT = "bodyrig-photoreal-frame-observations"
OBSERVATIONS_VERSION = 1
FORMAT = "bodyrig-photoreal-frame-index"
VERSION = 1

VALID_KINDS = {"video", "image"}
VALID_EYES = {"mono", "left", "right"}
VALID_VIEW_BINS = {
    "front",
    "three-quarter-left",
    "three-quarter-right",
    "profile-left",
    "profile-right",
    "rear",
    "unknown",
}
PERCEPTUAL_HASH_HEX_LENGTH = 16
MAX_CROSS_SPLIT_HASH_DISTANCE = 4
MIN_FACE_VISIBILITY = 0.72
MIN_FULL_BODY_VISIBILITY = 0.72
MIN_SHARPNESS = 0.35
MAX_OCCLUSION = 0.40
MAX_OBSERVATIONS = 250_000


class PhotorealFrameIndexError(ValueError):
    pass


@dataclass(frozen=True)
class _PlanSource:
    source_key: str
    split: str
    group_id: str
    kind: str


@dataclass
class _BkNode:
    value: int
    payload: str
    children: dict[int, "_BkNode"]


class _HammingBkTree:
    def __init__(self) -> None:
        self._root: _BkNode | None = None

    @staticmethod
    def _distance(left: int, right: int) -> int:
        return (left ^ right).bit_count()

    def add(self, value: int, payload: str) -> None:
        if self._root is None:
            self._root = _BkNode(value=value, payload=payload, children={})
            return
        node = self._root
        while True:
            distance = self._distance(value, node.value)
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BkNode(value=value, payload=payload, children={})
                return
            node = child

    def query(self, value: int, maximum_distance: int) -> list[tuple[int, str]]:
        if self._root is None:
            return []
        matches: list[tuple[int, str]] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            distance = self._distance(value, node.value)
            if distance <= maximum_distance:
                matches.append((distance, node.payload))
            lower = distance - maximum_distance
            upper = distance + maximum_distance
            for edge, child in node.children.items():
                if lower <= edge <= upper:
                    stack.append(child)
        return matches


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIndexError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIndexError(f"{label} must be a JSON object")
    return value


def _safe_text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealFrameIndexError(f"{label} is invalid")
    return result


def _hex(value: Any, *, length: int, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != length or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealFrameIndexError(f"{label} is invalid")
    return result


def _finite(value: Any, *, label: str, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise PhotorealFrameIndexError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIndexError(f"{label} is invalid") from exc
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise PhotorealFrameIndexError(f"{label} is outside its valid range")
    return result


def _integer(value: Any, *, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise PhotorealFrameIndexError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealFrameIndexError(f"{label} is invalid") from exc
    if result < minimum:
        raise PhotorealFrameIndexError(f"{label} is outside its valid range")
    return result


def _plan_sources(plan: Mapping[str, Any]) -> dict[str, _PlanSource]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealFrameIndexError("photoreal dataset plan format/version mismatch")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealFrameIndexError("photoreal dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealFrameIndexError("photoreal dataset plan crossed production authority")
    if plan.get("teacher_training_authorized") is not False:
        raise PhotorealFrameIndexError("frame analysis expects a pre-training dataset plan")

    result: dict[str, _PlanSource] = {}
    for split, key in (("train", "train"), ("evaluation", "evaluation")):
        values = plan.get(key)
        if not isinstance(values, list) or not values:
            raise PhotorealFrameIndexError(f"dataset plan {key} sources are invalid")
        for item in values:
            if not isinstance(item, Mapping):
                raise PhotorealFrameIndexError(f"dataset plan {key} contains a non-object source")
            source_key = _safe_text(item.get("source_id"), label="dataset source key")
            if source_key in result:
                raise PhotorealFrameIndexError(f"dataset plan repeats source key: {source_key}")
            kind = _safe_text(item.get("kind"), label="dataset source kind")
            if kind not in VALID_KINDS:
                raise PhotorealFrameIndexError(f"dataset source kind is unsupported: {kind}")
            result[source_key] = _PlanSource(
                source_key=source_key,
                split=split,
                group_id=_safe_text(item.get("group_id"), label="dataset group id"),
                kind=kind,
            )
    train_groups = {item.group_id for item in result.values() if item.split == "train"}
    eval_groups = {item.group_id for item in result.values() if item.split == "evaluation"}
    if train_groups & eval_groups:
        raise PhotorealFrameIndexError("dataset plan leaks source groups across train/evaluation")
    return result


def _receipt_sources(receipt: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("version") != RECEIPT_VERSION:
        raise PhotorealFrameIndexError("photoreal source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealFrameIndexError("photoreal source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealFrameIndexError("photoreal source receipt lacks path-specific source keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealFrameIndexError("photoreal source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealFrameIndexError("photoreal source receipt crossed production authority")

    values = receipt.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealFrameIndexError("photoreal source receipt contains no sources")
    result: dict[str, dict[str, str]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise PhotorealFrameIndexError("photoreal source receipt contains a non-object source")
        source_key = _safe_text(item.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealFrameIndexError(f"photoreal source receipt repeats source key: {source_key}")
        kind = _safe_text(item.get("kind"), label="receipt source kind")
        if kind not in VALID_KINDS:
            raise PhotorealFrameIndexError(f"receipt source kind is unsupported: {kind}")
        result[source_key] = {
            "kind": kind,
            "sha256": _hex(item.get("sha256"), length=64, label="receipt source SHA-256"),
        }
    return result


def _coverage_labels(view_bin: str, face_visibility: float, full_body_visibility: float) -> set[str]:
    result: set[str] = set()
    if view_bin == "front":
        if face_visibility >= MIN_FACE_VISIBILITY:
            result.add("face-front")
        if full_body_visibility >= MIN_FULL_BODY_VISIBILITY:
            result.add("full-body-front")
    elif view_bin in {"three-quarter-left", "three-quarter-right"}:
        if face_visibility >= MIN_FACE_VISIBILITY:
            result.add("face-three-quarter")
        if full_body_visibility >= MIN_FULL_BODY_VISIBILITY:
            result.add("full-body-three-quarter")
    elif view_bin in {"profile-left", "profile-right"}:
        if face_visibility >= MIN_FACE_VISIBILITY:
            result.add("face-profile")
        if full_body_visibility >= MIN_FULL_BODY_VISIBILITY:
            result.add("full-body-profile")
    elif view_bin == "rear" and full_body_visibility >= MIN_FULL_BODY_VISIBILITY:
        result.add("full-body-rear")
    return result


def _normalize_observation(
    raw: Mapping[str, Any],
    *,
    plan_source: _PlanSource,
    receipt_source: Mapping[str, str],
) -> dict[str, Any]:
    source_key = _safe_text(raw.get("source_key"), label="frame source key")
    if source_key != plan_source.source_key:
        raise PhotorealFrameIndexError("frame source key changed during normalization")
    source_sha = _hex(raw.get("source_sha256"), length=64, label="frame source SHA-256")
    if source_sha != receipt_source["sha256"]:
        raise PhotorealFrameIndexError(f"frame observation targets different source bytes: {source_key}")
    kind = _safe_text(raw.get("kind"), label="frame source kind")
    if kind != plan_source.kind or kind != receipt_source["kind"]:
        raise PhotorealFrameIndexError(f"frame source kind mismatch: {source_key}")

    view_bin = _safe_text(raw.get("view_bin"), label="frame view bin")
    if view_bin not in VALID_VIEW_BINS:
        raise PhotorealFrameIndexError(f"unsupported frame view bin: {view_bin}")
    eye = _safe_text(raw.get("eye"), label="frame eye")
    if eye not in VALID_EYES:
        raise PhotorealFrameIndexError(f"unsupported frame eye: {eye}")

    timestamp_raw = raw.get("timestamp_seconds")
    if kind == "video":
        timestamp = _finite(timestamp_raw, label="frame timestamp", minimum=0.0)
    else:
        if timestamp_raw is not None:
            raise PhotorealFrameIndexError("still-image observation must not carry a video timestamp")
        timestamp = None

    face_visibility = _finite(raw.get("face_visibility"), label="face visibility", maximum=1.0)
    full_body_visibility = _finite(raw.get("full_body_visibility"), label="full-body visibility", maximum=1.0)
    sharpness = _finite(raw.get("sharpness"), label="frame sharpness", maximum=1.0)
    motion = _finite(raw.get("motion"), label="frame motion", maximum=1.0)
    occlusion = _finite(raw.get("occlusion"), label="frame occlusion", maximum=1.0)
    person_fraction = _finite(raw.get("person_fraction"), label="person fraction", maximum=1.0)
    identity_confidence = _finite(raw.get("identity_confidence"), label="identity confidence", maximum=1.0)
    target_identity_verified = raw.get("target_identity_verified")
    if not isinstance(target_identity_verified, bool):
        raise PhotorealFrameIndexError("target_identity_verified must be boolean")

    eligible = target_identity_verified and sharpness >= MIN_SHARPNESS and occlusion <= MAX_OCCLUSION
    coverage = sorted(_coverage_labels(view_bin, face_visibility, full_body_visibility)) if eligible else []

    return {
        "source_key": source_key,
        "source_sha256": source_sha,
        "split": plan_source.split,
        "group_id": plan_source.group_id,
        "kind": kind,
        "timestamp_seconds": None if timestamp is None else round(timestamp, 6),
        "eye": eye,
        "projection": str(raw.get("projection") or "unknown"),
        "frame_sha256": _hex(raw.get("frame_sha256"), length=64, label="frame SHA-256"),
        "perceptual_hash": _hex(raw.get("perceptual_hash"), length=PERCEPTUAL_HASH_HEX_LENGTH, label="frame perceptual hash"),
        "width": _integer(raw.get("width"), label="frame width"),
        "height": _integer(raw.get("height"), label="frame height"),
        "view_bin": view_bin,
        "face_visibility": round(face_visibility, 6),
        "full_body_visibility": round(full_body_visibility, 6),
        "person_fraction": round(person_fraction, 6),
        "sharpness": round(sharpness, 6),
        "motion": round(motion, 6),
        "occlusion": round(occlusion, 6),
        "identity_confidence": round(identity_confidence, 6),
        "target_identity_verified": target_identity_verified,
        "eligible_for_teacher": eligible,
        "coverage": coverage,
    }


def _cross_split_near_duplicates(observations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    evaluation = [item for item in observations if item["split"] == "evaluation" and item["eligible_for_teacher"]]
    train = [item for item in observations if item["split"] == "train" and item["eligible_for_teacher"]]
    tree = _HammingBkTree()
    eval_by_payload: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(evaluation):
        payload = f"eval:{index}"
        eval_by_payload[payload] = item
        tree.add(int(str(item["perceptual_hash"]), 16), payload)

    pairs: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str, str]] = set()
    for item in train:
        for distance, payload in tree.query(int(str(item["perceptual_hash"]), 16), MAX_CROSS_SPLIT_HASH_DISTANCE):
            other = eval_by_payload[payload]
            key = (
                str(item["source_key"]),
                str(item["frame_sha256"]),
                str(other["source_key"]),
                str(other["frame_sha256"]),
            )
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append(
                {
                    "distance": distance,
                    "train_source_key": item["source_key"],
                    "train_frame_sha256": item["frame_sha256"],
                    "evaluation_source_key": other["source_key"],
                    "evaluation_frame_sha256": other["frame_sha256"],
                }
            )
    pairs.sort(key=lambda item: (int(item["distance"]), str(item["train_source_key"]), str(item["evaluation_source_key"])))
    return pairs


def build_frame_index(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    analyzer_output: Mapping[str, Any],
) -> dict[str, Any]:
    plan_sources = _plan_sources(plan)
    receipt_sources = _receipt_sources(receipt)
    if set(plan_sources) != set(receipt_sources):
        missing_receipt = sorted(set(plan_sources) - set(receipt_sources))
        extra_receipt = sorted(set(receipt_sources) - set(plan_sources))
        raise PhotorealFrameIndexError(
            f"dataset plan/source receipt disagree on exact source universe "
            f"(missing_receipt={len(missing_receipt)}, extra_receipt={len(extra_receipt)})"
        )
    if str(plan.get("performer_id") or "") != str(receipt.get("performer_id") or ""):
        raise PhotorealFrameIndexError("dataset plan/source receipt performer mismatch")

    if analyzer_output.get("format") != OBSERVATIONS_FORMAT or analyzer_output.get("version") != OBSERVATIONS_VERSION:
        raise PhotorealFrameIndexError("photoreal frame observations format/version mismatch")
    if analyzer_output.get("build_only") is not True or analyzer_output.get("production_activation") is not False:
        raise PhotorealFrameIndexError("photoreal frame observations authority boundary is invalid")
    if str(analyzer_output.get("performer_id") or "") != str(plan.get("performer_id") or ""):
        raise PhotorealFrameIndexError("photoreal frame observations performer mismatch")
    analyzer = _safe_text(analyzer_output.get("analyzer"), label="frame analyzer", maximum=256)
    analyzer_revision = _safe_text(analyzer_output.get("analyzer_revision"), label="frame analyzer revision", maximum=256)

    raw_observations = analyzer_output.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise PhotorealFrameIndexError("photoreal frame observations are empty")
    if len(raw_observations) > MAX_OBSERVATIONS:
        raise PhotorealFrameIndexError(f"photoreal frame observations exceed explicit safety bound {MAX_OBSERVATIONS}")

    normalized: list[dict[str, Any]] = []
    observed_sources: set[str] = set()
    seen_frame_keys: set[tuple[str, str, str]] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise PhotorealFrameIndexError("photoreal frame observations contain a non-object")
        source_key = _safe_text(raw.get("source_key"), label="frame source key")
        plan_source = plan_sources.get(source_key)
        receipt_source = receipt_sources.get(source_key)
        if plan_source is None or receipt_source is None:
            raise PhotorealFrameIndexError(f"frame observation references unknown source: {source_key}")
        item = _normalize_observation(raw, plan_source=plan_source, receipt_source=receipt_source)
        frame_identity = (item["source_key"], str(item["timestamp_seconds"]), item["eye"])
        if frame_identity in seen_frame_keys:
            raise PhotorealFrameIndexError(f"duplicate frame observation identity: {frame_identity}")
        seen_frame_keys.add(frame_identity)
        observed_sources.add(source_key)
        normalized.append(item)

    missing_sources = sorted(set(plan_sources) - observed_sources)
    if missing_sources:
        raise PhotorealFrameIndexError(f"frame analyzer did not cover every planned source ({len(missing_sources)} missing)")

    normalized.sort(
        key=lambda item: (
            item["split"],
            item["group_id"],
            item["source_key"],
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            item["eye"],
        )
    )
    duplicates = _cross_split_near_duplicates(normalized)

    eval_eligible = [item for item in normalized if item["split"] == "evaluation" and item["eligible_for_teacher"]]
    train_eligible = [item for item in normalized if item["split"] == "train" and item["eligible_for_teacher"]]
    eval_coverage = sorted({label for item in eval_eligible for label in item["coverage"]})
    all_coverage = sorted({label for item in normalized if item["eligible_for_teacher"] for label in item["coverage"]})

    required = list(plan.get("held_out_view_coverage_required") or [])
    if not required or not all(isinstance(item, str) and item for item in required):
        raise PhotorealFrameIndexError("dataset plan held-out view coverage requirements are invalid")
    rear_observable = "full-body-rear" in all_coverage
    if plan.get("rear_view_required_when_source_observable") is not True:
        raise PhotorealFrameIndexError("dataset plan rear-view policy is invalid")
    effective_required = list(dict.fromkeys(required + (["full-body-rear"] if rear_observable else [])))
    missing_eval_coverage = sorted(set(effective_required) - set(eval_coverage))

    training_authorized = (
        bool(train_eligible)
        and bool(eval_eligible)
        and not duplicates
        and not missing_eval_coverage
        and len(observed_sources) == len(plan_sources)
    )
    blockers: list[str] = []
    if not train_eligible:
        blockers.append("no eligible training observations")
    if not eval_eligible:
        blockers.append("no eligible evaluation observations")
    if duplicates:
        blockers.append("cross-split perceptual near-duplicates detected")
    if missing_eval_coverage:
        blockers.append("held-out evaluation view coverage is incomplete")

    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": str(plan.get("performer_id") or ""),
        "performer_name": str(plan.get("performer_name") or ""),
        "analyzer": analyzer,
        "analyzer_revision": analyzer_revision,
        "source_count": len(plan_sources),
        "observed_source_count": len(observed_sources),
        "observation_count": len(normalized),
        "eligible_train_observation_count": len(train_eligible),
        "eligible_evaluation_observation_count": len(eval_eligible),
        "perceptual_hash_algorithm_contract": "64-bit-hamming-v1",
        "cross_split_max_hamming_distance": MAX_CROSS_SPLIT_HASH_DISTANCE,
        "cross_split_near_duplicate_count": len(duplicates),
        "cross_split_near_duplicates": duplicates,
        "held_out_view_coverage_required": effective_required,
        "held_out_view_coverage_observed": eval_coverage,
        "held_out_view_coverage_missing": missing_eval_coverage,
        "rear_view_source_observable": rear_observable,
        "thresholds": {
            "minimum_face_visibility": MIN_FACE_VISIBILITY,
            "minimum_full_body_visibility": MIN_FULL_BODY_VISIBILITY,
            "minimum_sharpness": MIN_SHARPNESS,
            "maximum_occlusion": MAX_OCCLUSION,
        },
        "observations": normalized,
        "teacher_training_authorized": training_authorized,
        "training_blockers": blockers,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_frame_index_files(
    plan_path: str | Path,
    receipt_path: str | Path,
    observations_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    observations = _read_json(observations_path, label="photoreal frame observations")
    result = build_frame_index(plan, receipt, observations)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIndexError(f"photoreal frame index already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
