from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .photoidentity_schp_contract import ADAPTER, ADAPTER_REVISION, LABELS


class PhotoIdentitySchpDetailError(ValueError):
    pass


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentitySchpDetailError(f"{label} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise PhotoIdentitySchpDetailError(f"{label} must be in 0..1") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentitySchpDetailError(f"{label} must be in 0..1")
    return result


def _normalize_map(segmentation: Sequence[Sequence[object]]) -> tuple[list[list[int]], int, int]:
    rows = [list(row) for row in segmentation]
    if not rows or not rows[0]:
        raise PhotoIdentitySchpDetailError("SCHP segmentation map is empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise PhotoIdentitySchpDetailError("SCHP segmentation map is ragged")
    if len(rows) != 512 or width != 512:
        raise PhotoIdentitySchpDetailError("SCHP segmentation map must be exactly 512x512")
    normalized: list[list[int]] = []
    for row in rows:
        target: list[int] = []
        for value in row:
            if isinstance(value, bool):
                raise PhotoIdentitySchpDetailError("SCHP segmentation contains boolean label")
            try:
                label = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PhotoIdentitySchpDetailError("SCHP segmentation contains non-integer label") from exc
            if label not in LABELS:
                raise PhotoIdentitySchpDetailError(f"SCHP segmentation contains unknown label {label}")
            target.append(label)
        normalized.append(target)
    return normalized, width, len(rows)


def _stats(segmentation: Sequence[Sequence[int]]) -> tuple[dict[int, int], dict[int, tuple[int, int, int, int]]]:
    counts: dict[int, int] = {}
    boxes: dict[int, tuple[int, int, int, int]] = {}
    for y, row in enumerate(segmentation):
        for x, label in enumerate(row):
            counts[label] = counts.get(label, 0) + 1
            box = boxes.get(label)
            if box is None:
                boxes[label] = (x, y, x, y)
            else:
                boxes[label] = (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
    return counts, boxes


def _bbox_source_extent(
    box: tuple[int, int, int, int] | None,
    *,
    source_width: int,
    source_height: int,
) -> tuple[float, float, float]:
    if box is None:
        return 0.0, 0.0, 0.0
    width = max(1, box[2] - box[0] + 1) * source_width / 512.0
    height = max(1, box[3] - box[1] + 1) * source_height / 512.0
    return width, height, math.hypot(width, height)


def _x_overlap_fraction(a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int] | None) -> float:
    if a is None or b is None:
        return 0.0
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]) + 1)
    b_width = max(1, b[2] - b[0] + 1)
    return min(1.0, overlap / b_width)


def _hair_face_proximity(hair: tuple[int, int, int, int] | None, face: tuple[int, int, int, int] | None) -> float:
    if hair is None or face is None:
        return 0.0
    overlap = _x_overlap_fraction(hair, face)
    vertical_gap = max(0, face[1] - hair[3] - 1)
    gap_score = max(0.0, 1.0 - vertical_gap / 20.0)
    return min(overlap, gap_score)


def _claim(scene_id: str, quality: float) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "quality": round(max(0.0, min(1.0, quality)), 4),
        "source_derived": True,
        "adapter": ADAPTER,
        "revision": ADAPTER_REVISION,
    }


def analyze_schp_detail(
    segmentation: Sequence[Sequence[object]],
    *,
    scene_id: str,
    observation: Mapping[str, Any],
    source_width: int,
    source_height: int,
) -> dict[str, list[dict[str, object]]]:
    """Prove only source observability supported by ATR semantic parsing.

    Hair/hairline requires a real Hair mask adjacent to a real Face mask and a
    sufficiently large source-space hair region. Skin detail requires exposed
    face plus independently segmented arm/leg pixels. No anatomy, orientation
    or nail authority is inferred from these masks.
    """

    scene = str(scene_id or "").strip()
    if not scene or len(scene) > 256:
        raise PhotoIdentitySchpDetailError("scene_id is invalid")
    for value, label in ((source_width, "source_width"), (source_height, "source_height")):
        if isinstance(value, bool) or not isinstance(value, int) or not 128 <= value <= 16384:
            raise PhotoIdentitySchpDetailError(f"{label} is invalid")

    sharpness = _finite(observation.get("sharpness"), label="observation sharpness")
    occlusion = _finite(observation.get("occlusion"), label="observation occlusion")
    target_confidence = _finite(observation.get("target_confidence"), label="target confidence")
    face_visibility = _finite(observation.get("face_visibility"), label="face visibility")
    full_body_visibility = _finite(observation.get("full_body_visibility"), label="full-body visibility")

    seg, _, _ = _normalize_map(segmentation)
    counts, boxes = _stats(seg)
    total = 512 * 512
    claims: dict[str, list[dict[str, object]]] = {}

    hair_count = counts.get(2, 0)
    face_count = counts.get(11, 0)
    hair_extent = _bbox_source_extent(boxes.get(2), source_width=source_width, source_height=source_height)[2]
    proximity = _hair_face_proximity(boxes.get(2), boxes.get(11))
    hair_area_score = min(1.0, hair_count / (total * 0.025))
    face_area_score = min(1.0, face_count / (total * 0.012))
    hair_resolution_score = min(1.0, hair_extent / 260.0)
    if (
        target_confidence >= 0.80
        and face_visibility >= 0.78
        and hair_count > 0
        and face_count > 0
        and proximity >= 0.55
    ):
        quality = min(
            target_confidence,
            face_visibility,
            sharpness,
            1.0 - occlusion,
            hair_area_score,
            face_area_score,
            hair_resolution_score,
            proximity,
        )
        claims["hair_hairline"] = [_claim(scene, quality)]

    exposed_labels = (11, 12, 13, 14, 15)  # face + left/right leg + left/right arm
    exposed_count = sum(counts.get(label, 0) for label in exposed_labels)
    limb_labels = [label for label in (12, 13, 14, 15) if counts.get(label, 0) >= total * 0.004]
    exposed_boxes = [boxes[label] for label in exposed_labels if label in boxes]
    if exposed_boxes:
        aggregate = (
            min(box[0] for box in exposed_boxes),
            min(box[1] for box in exposed_boxes),
            max(box[2] for box in exposed_boxes),
            max(box[3] for box in exposed_boxes),
        )
    else:
        aggregate = None
    exposed_extent = _bbox_source_extent(aggregate, source_width=source_width, source_height=source_height)[2]
    exposed_area_score = min(1.0, exposed_count / (total * 0.10))
    exposed_resolution_score = min(1.0, exposed_extent / 600.0)
    region_diversity_score = min(1.0, len(limb_labels) / 2.0)
    if (
        target_confidence >= 0.78
        and full_body_visibility >= 0.70
        and face_count >= total * 0.008
        and len(limb_labels) >= 2
    ):
        quality = min(
            target_confidence,
            full_body_visibility,
            sharpness,
            1.0 - occlusion,
            exposed_area_score,
            exposed_resolution_score,
            region_diversity_score,
        )
        claims["skin_detail"] = [_claim(scene, quality)]

    return claims
