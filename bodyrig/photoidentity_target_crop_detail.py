from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .photoidentity_openpose_detail import _confident, _diagonal, _mean_confidence, _triples
from .photoidentity_schp_detail import _bbox_source_extent, _hair_face_proximity, _normalize_map, _stats

OPENPOSE_ADAPTER = "openpose-body25-face-hand-target-crop-observability"
OPENPOSE_REVISION = "1"
SCHP_ADAPTER = "schp-atr18-target-crop-observability"
SCHP_REVISION = "1"
SUPPORTED_DOMAINS = frozenset({"eyes_detail", "hands", "feet", "hair_hairline", "skin_detail"})


class PhotoIdentityTargetCropDetailError(ValueError):
    pass


def _candidate(domain: str, score: float, *, adapter: str, revision: str, metrics: Mapping[str, object]) -> dict[str, object]:
    if domain not in SUPPORTED_DOMAINS:
        raise PhotoIdentityTargetCropDetailError(f"unsupported target-crop domain: {domain}")
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise PhotoIdentityTargetCropDetailError(f"target-crop score for {domain} is invalid")
    return {
        "domain": domain,
        "machine_observability_score": round(score, 4),
        "source_derived": True,
        "adapter": adapter,
        "revision": revision,
        "source_detail_quality_authority": False,
        "photoidentity_sufficiency_authority": False,
        "metrics": dict(metrics),
    }


def analyze_openpose_target_crop(payload: Mapping[str, Any], *, width: int, height: int) -> list[dict[str, object]]:
    if isinstance(width, bool) or not isinstance(width, int) or not 64 <= width <= 16384:
        raise PhotoIdentityTargetCropDetailError("target-crop width is invalid")
    if isinstance(height, bool) or not isinstance(height, int) or not 64 <= height <= 16384:
        raise PhotoIdentityTargetCropDetailError("target-crop height is invalid")
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        return []
    person = people[0]
    try:
        body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected_points=25)
        left_hand = _triples(person.get("hand_left_keypoints_2d"), label="left hand", expected_points=21)
        right_hand = _triples(person.get("hand_right_keypoints_2d"), label="right hand", expected_points=21)
        face = _triples(person.get("face_keypoints_2d"), label="face", expected_points=70)
    except Exception as exc:
        raise PhotoIdentityTargetCropDetailError(str(exc)) from exc

    result: list[dict[str, object]] = []
    left_eye = _confident(face[36:42], threshold=0.25, width=width, height=height)
    right_eye = _confident(face[42:48], threshold=0.25, width=width, height=height)
    eye_extent = _diagonal([*left_eye, *right_eye])
    if len(left_eye) >= 5 and len(right_eye) >= 5:
        confidence = min(_mean_confidence(left_eye), _mean_confidence(right_eye))
        resolution = min(1.0, eye_extent / 110.0)
        result.append(_candidate(
            "eyes_detail",
            min(confidence, resolution),
            adapter=OPENPOSE_ADAPTER,
            revision=OPENPOSE_REVISION,
            metrics={"left_points": len(left_eye), "right_points": len(right_eye), "confidence": round(confidence, 4), "pixel_extent": round(eye_extent, 3), "resolution_score": round(resolution, 4)},
        ))

    left = _confident(left_hand, threshold=0.20, width=width, height=height)
    right = _confident(right_hand, threshold=0.20, width=width, height=height)
    if len(left) >= 16 and len(right) >= 16:
        confidence = min(_mean_confidence(left), _mean_confidence(right))
        pixel_extent = min(_diagonal(left), _diagonal(right))
        resolution = min(1.0, pixel_extent / 120.0)
        result.append(_candidate(
            "hands",
            min(confidence, resolution),
            adapter=OPENPOSE_ADAPTER,
            revision=OPENPOSE_REVISION,
            metrics={"left_points": len(left), "right_points": len(right), "confidence": round(confidence, 4), "minimum_hand_pixel_extent": round(pixel_extent, 3), "resolution_score": round(resolution, 4)},
        ))

    left_foot = _confident(body[19:22], threshold=0.20, width=width, height=height)
    right_foot = _confident(body[22:25], threshold=0.20, width=width, height=height)
    if len(left_foot) == 3 and len(right_foot) == 3:
        confidence = min(_mean_confidence(left_foot), _mean_confidence(right_foot))
        pixel_extent = min(_diagonal(left_foot), _diagonal(right_foot))
        resolution = min(1.0, pixel_extent / 70.0)
        result.append(_candidate(
            "feet",
            min(confidence, resolution),
            adapter=OPENPOSE_ADAPTER,
            revision=OPENPOSE_REVISION,
            metrics={"left_points": 3, "right_points": 3, "confidence": round(confidence, 4), "minimum_foot_pixel_extent": round(pixel_extent, 3), "resolution_score": round(resolution, 4)},
        ))
    return result


def analyze_schp_target_crop(segmentation: Sequence[Sequence[object]], *, source_width: int, source_height: int) -> list[dict[str, object]]:
    if isinstance(source_width, bool) or not isinstance(source_width, int) or not 128 <= source_width <= 16384:
        raise PhotoIdentityTargetCropDetailError("target-crop source width is invalid")
    if isinstance(source_height, bool) or not isinstance(source_height, int) or not 128 <= source_height <= 16384:
        raise PhotoIdentityTargetCropDetailError("target-crop source height is invalid")
    try:
        seg, _, _ = _normalize_map(segmentation)
        counts, boxes = _stats(seg)
    except Exception as exc:
        raise PhotoIdentityTargetCropDetailError(str(exc)) from exc
    total = 512 * 512
    result: list[dict[str, object]] = []

    hair_count = counts.get(2, 0)
    face_count = counts.get(11, 0)
    hair_extent = _bbox_source_extent(boxes.get(2), source_width=source_width, source_height=source_height)[2]
    proximity = _hair_face_proximity(boxes.get(2), boxes.get(11))
    hair_area = min(1.0, hair_count / (total * 0.025))
    face_area = min(1.0, face_count / (total * 0.012))
    hair_resolution = min(1.0, hair_extent / 260.0)
    if hair_count > 0 and face_count > 0 and proximity >= 0.55:
        result.append(_candidate(
            "hair_hairline",
            min(hair_area, face_area, hair_resolution, proximity),
            adapter=SCHP_ADAPTER,
            revision=SCHP_REVISION,
            metrics={"hair_fraction": round(hair_count / total, 6), "face_fraction": round(face_count / total, 6), "hair_pixel_extent": round(hair_extent, 3), "hair_face_proximity": round(proximity, 4)},
        ))

    exposed_labels = (11, 12, 13, 14, 15)
    exposed_count = sum(counts.get(label, 0) for label in exposed_labels)
    limb_labels = [label for label in (12, 13, 14, 15) if counts.get(label, 0) >= total * 0.004]
    exposed_boxes = [boxes[label] for label in exposed_labels if label in boxes]
    aggregate = None
    if exposed_boxes:
        aggregate = (min(box[0] for box in exposed_boxes), min(box[1] for box in exposed_boxes), max(box[2] for box in exposed_boxes), max(box[3] for box in exposed_boxes))
    exposed_extent = _bbox_source_extent(aggregate, source_width=source_width, source_height=source_height)[2]
    area_score = min(1.0, exposed_count / (total * 0.10))
    resolution = min(1.0, exposed_extent / 600.0)
    diversity = min(1.0, len(limb_labels) / 2.0)
    if face_count >= total * 0.008 and len(limb_labels) >= 2:
        result.append(_candidate(
            "skin_detail",
            min(area_score, resolution, diversity),
            adapter=SCHP_ADAPTER,
            revision=SCHP_REVISION,
            metrics={"exposed_fraction": round(exposed_count / total, 6), "qualifying_limb_regions": len(limb_labels), "exposed_pixel_extent": round(exposed_extent, 3), "area_score": round(area_score, 4), "resolution_score": round(resolution, 4)},
        ))
    return result
