from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

INVENTORY_FORMAT = "bodyrig-photoreal-source-inventory"
INVENTORY_VERSION = 1
FORMAT = "bodyrig-photoreal-dataset-plan"
VERSION = 1
DEFAULT_EVAL_FRACTION = 0.20
MIN_GROUPS = 2


class PhotorealDatasetPlanError(ValueError):
    pass


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealDatasetPlanError(f"photoreal source inventory is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise PhotorealDatasetPlanError("photoreal source inventory must be a JSON object")
    return value


def _require_inventory(inventory: Mapping[str, Any]) -> None:
    if inventory.get("format") != INVENTORY_FORMAT or inventory.get("version") != INVENTORY_VERSION:
        raise PhotorealDatasetPlanError("photoreal source inventory format/version mismatch")
    if inventory.get("build_only") is not True:
        raise PhotorealDatasetPlanError("photoreal source inventory must remain build-only")
    if inventory.get("photoreal_teacher_input") is not True:
        raise PhotorealDatasetPlanError("photoreal source inventory is not teacher input")
    if inventory.get("runtime_dependency") is not False or inventory.get("production_activation") is not False:
        raise PhotorealDatasetPlanError("photoreal source inventory crossed its authority boundary")
    performer_id = str(inventory.get("performer_id") or "").strip()
    performer_name = str(inventory.get("performer_name") or "").strip()
    performer = inventory.get("performer")
    if not performer_id or not performer_name or not isinstance(performer, Mapping):
        raise PhotorealDatasetPlanError("photoreal source inventory performer identity is incomplete")
    if str(performer.get("id") or "").strip() != performer_id or str(performer.get("name") or "").strip() != performer_name:
        raise PhotorealDatasetPlanError("photoreal source inventory performer identity is inconsistent")
    videos = inventory.get("videos")
    images = inventory.get("images")
    if not isinstance(videos, list) or not isinstance(images, list):
        raise PhotorealDatasetPlanError("photoreal source inventory videos/images are invalid")


def _safe_id(value: Any, *, label: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 4096:
        raise PhotorealDatasetPlanError(f"{label} is invalid")
    return result


def _score(value: Any) -> float:
    if isinstance(value, bool):
        raise PhotorealDatasetPlanError("source information_score cannot be boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealDatasetPlanError("source information_score is invalid") from exc
    if not math.isfinite(result) or result < 0:
        raise PhotorealDatasetPlanError("source information_score must be finite and non-negative")
    return result


def _source_group_for_image(image: Mapping[str, Any]) -> str:
    gallery_ids = image.get("gallery_ids") or []
    if not isinstance(gallery_ids, list):
        raise PhotorealDatasetPlanError("image gallery_ids must be an array")
    normalized = sorted({_safe_id(item, label="gallery id") for item in gallery_ids})
    if normalized:
        return "gallery:" + "+".join(normalized)
    return "image:" + _safe_id(image.get("image_id"), label="image id")


def _source_records(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for video in inventory.get("videos") or []:
        if not isinstance(video, Mapping):
            raise PhotorealDatasetPlanError("video source must be an object")
        scene_id = _safe_id(video.get("scene_id"), label="scene id")
        path = _safe_id(video.get("path"), label="video path")
        key = ("video", path.casefold())
        if key in seen:
            raise PhotorealDatasetPlanError(f"duplicate video source path: {path}")
        seen.add(key)
        records.append(
            {
                "kind": "video",
                "source_id": f"scene:{scene_id}:{path}",
                "group_id": f"scene:{scene_id}",
                "path": path,
                "information_score": _score(video.get("information_score")),
                "projection": str(video.get("projection") or "unknown"),
                "stereo_layout": str(video.get("stereo_layout") or "unknown"),
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
                "duration_seconds": float(video.get("duration_seconds") or 0.0),
                "frame_rate": float(video.get("frame_rate") or 0.0),
            }
        )

    for image in inventory.get("images") or []:
        if not isinstance(image, Mapping):
            raise PhotorealDatasetPlanError("image source must be an object")
        image_id = _safe_id(image.get("image_id"), label="image id")
        path = _safe_id(image.get("path"), label="image path")
        key = ("image", path.casefold())
        if key in seen:
            raise PhotorealDatasetPlanError(f"duplicate image source path: {path}")
        seen.add(key)
        records.append(
            {
                "kind": "image",
                "source_id": f"image:{image_id}:{path}",
                "group_id": _source_group_for_image(image),
                "path": path,
                "information_score": _score(image.get("information_score")),
                "source_binding": str(image.get("source_binding") or "unknown"),
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
                "megapixels": float(image.get("megapixels") or 0.0),
            }
        )

    if not records:
        raise PhotorealDatasetPlanError("photoreal source inventory contains no usable media")
    return records


def _stable_rank(seed: str, group_id: str) -> str:
    return hashlib.sha256(f"{seed}\n{group_id}".encode("utf-8")).hexdigest()


def build_dataset_plan(
    inventory: Mapping[str, Any],
    *,
    eval_fraction: float = DEFAULT_EVAL_FRACTION,
    seed: str = "bodyrig-photoreal-v2",
) -> dict[str, Any]:
    _require_inventory(inventory)
    if isinstance(eval_fraction, bool) or not isinstance(eval_fraction, (int, float)):
        raise PhotorealDatasetPlanError("eval_fraction must be numeric")
    eval_fraction = float(eval_fraction)
    if not 0.10 <= eval_fraction <= 0.40:
        raise PhotorealDatasetPlanError("eval_fraction must be in 0.10..0.40")
    seed = str(seed or "").strip()
    if not seed or len(seed) > 256:
        raise PhotorealDatasetPlanError("dataset split seed is invalid")

    records = _source_records(inventory)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record["group_id"])].append(record)
    if len(groups) < MIN_GROUPS:
        raise PhotorealDatasetPlanError(
            "photoreal teacher requires at least two independent source groups so evaluation can be held out"
        )

    ranked_groups = sorted(groups, key=lambda group_id: (_stable_rank(seed, group_id), group_id))
    eval_count = max(1, int(round(len(ranked_groups) * eval_fraction)))
    eval_count = min(eval_count, len(ranked_groups) - 1)
    eval_groups = set(ranked_groups[:eval_count])
    train_groups = set(ranked_groups[eval_count:])
    if not eval_groups or not train_groups or eval_groups & train_groups:
        raise PhotorealDatasetPlanError("dataset group split is invalid")

    train: list[dict[str, Any]] = []
    evaluation: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: (str(item["group_id"]), str(item["source_id"]))):
        target = evaluation if record["group_id"] in eval_groups else train
        target.append(dict(record))

    train_group_ids = {str(item["group_id"]) for item in train}
    eval_group_ids = {str(item["group_id"]) for item in evaluation}
    if train_group_ids & eval_group_ids:
        raise PhotorealDatasetPlanError("train/evaluation source-group leakage detected")

    train_score = round(sum(float(item["information_score"]) for item in train), 3)
    eval_score = round(sum(float(item["information_score"]) for item in evaluation), 3)
    total_score = train_score + eval_score

    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _safe_id(inventory.get("performer_id"), label="performer id"),
        "performer_name": str(inventory.get("performer_name") or ""),
        "split_seed": seed,
        "requested_eval_fraction": round(eval_fraction, 4),
        "group_count": len(groups),
        "train_group_count": len(train_group_ids),
        "evaluation_group_count": len(eval_group_ids),
        "train_source_count": len(train),
        "evaluation_source_count": len(evaluation),
        "train_information_score": train_score,
        "evaluation_information_score": eval_score,
        "information_score_total": round(total_score, 3),
        "leakage_policy": "source-group-disjoint-v1",
        "grouping_policy": {
            "video": "all files from one Stash scene stay together",
            "gallery_image": "all images sharing the same performer gallery stay together",
            "direct_image": "ungalleried image is its own source group",
        },
        "train": train,
        "evaluation": evaluation,
        "view_analysis_required": True,
        "held_out_view_coverage_required": [
            "face-front",
            "face-three-quarter",
            "face-profile",
            "full-body-front",
            "full-body-three-quarter",
        ],
        "rear_view_required_when_source_observable": True,
        "teacher_training_authorized": False,
        "reason_training_not_authorized": "frame/view analysis and held-out coverage have not been proven yet",
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_dataset_plan_file(
    inventory_path: str | Path,
    output_path: str | Path,
    *,
    eval_fraction: float = DEFAULT_EVAL_FRACTION,
    seed: str = "bodyrig-photoreal-v2",
) -> dict[str, Any]:
    inventory = _read_json(inventory_path)
    result = build_dataset_plan(inventory, eval_fraction=eval_fraction, seed=seed)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealDatasetPlanError(f"dataset plan output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
