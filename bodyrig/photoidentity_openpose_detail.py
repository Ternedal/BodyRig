from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

ADAPTER = "openpose-body25-face-hand-detail"
REVISION = "1"
CAPABILITIES = ("eyes-detail", "hands-detail", "feet-detail")


class PhotoIdentityOpenPoseDetailError(ValueError):
    pass


def _finite(value: object, *, label: str, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityOpenPoseDetailError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PhotoIdentityOpenPoseDetailError(f"{label} must be in {minimum}..{maximum}")
    return result


def _triples(value: object, *, label: str, expected_points: int) -> list[tuple[float, float, float]]:
    if not isinstance(value, list) or len(value) != expected_points * 3:
        raise PhotoIdentityOpenPoseDetailError(
            f"OpenPose {label} must contain exactly {expected_points * 3} numeric values"
        )
    result: list[tuple[float, float, float]] = []
    for index in range(expected_points):
        chunk = value[index * 3 : index * 3 + 3]
        try:
            x, y, confidence = (float(item) for item in chunk)
        except (TypeError, ValueError) as exc:
            raise PhotoIdentityOpenPoseDetailError(f"OpenPose {label} contains non-numeric values") from exc
        if not all(math.isfinite(item) for item in (x, y, confidence)) or not 0.0 <= confidence <= 1.0:
            raise PhotoIdentityOpenPoseDetailError(f"OpenPose {label} contains invalid coordinates/confidence")
        result.append((x, y, confidence))
    return result


def _confident(
    points: Sequence[tuple[float, float, float]],
    *,
    threshold: float,
    width: int,
    height: int,
) -> list[tuple[float, float, float]]:
    return [
        point
        for point in points
        if point[2] >= threshold and 0.0 <= point[0] < float(width) and 0.0 <= point[1] < float(height)
    ]


def _mean_confidence(points: Sequence[tuple[float, float, float]]) -> float:
    if not points:
        return 0.0
    return sum(point[2] for point in points) / len(points)


def _diagonal(points: Sequence[tuple[float, float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _quality(*, confidence: float, pixel_extent: float, required_pixels: float, sharpness: float, occlusion: float) -> float:
    resolution = min(1.0, max(0.0, pixel_extent) / required_pixels)
    visibility = max(0.0, 1.0 - occlusion)
    # A detail claim is only as strong as its weakest source-derived leg. This
    # intentionally prevents high keypoint confidence from compensating for a
    # tiny/blurry/occluded source crop.
    return round(min(confidence, resolution, sharpness, visibility), 4)


def _claim(scene_id: str, quality: float) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "quality": quality,
        "source_derived": True,
        "adapter": ADAPTER,
        "revision": REVISION,
    }


def analyze_openpose_detail(
    payload: Mapping[str, Any],
    *,
    scene_id: str,
    observation: Mapping[str, Any],
    frame_width: int,
    frame_height: int,
) -> dict[str, list[dict[str, object]]]:
    """Return conservative source-detail claims from one exact video frame.

    This adapter proves *observability*, not reconstructed identity. It never
    claims hair, skin, torso/chest anatomy or nails: OpenPose has no authority
    for those domains. Those remain fail-closed until a purpose-built analyzer
    is pinned and reviewed.
    """

    scene = str(scene_id or "").strip()
    if not scene or len(scene) > 256:
        raise PhotoIdentityOpenPoseDetailError("scene_id is invalid")
    if isinstance(frame_width, bool) or not isinstance(frame_width, int) or not 64 <= frame_width <= 16384:
        raise PhotoIdentityOpenPoseDetailError("frame_width is invalid")
    if isinstance(frame_height, bool) or not isinstance(frame_height, int) or not 64 <= frame_height <= 16384:
        raise PhotoIdentityOpenPoseDetailError("frame_height is invalid")

    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        return {}
    person = people[0]
    body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected_points=25)
    left_hand = _triples(person.get("hand_left_keypoints_2d"), label="left hand", expected_points=21)
    right_hand = _triples(person.get("hand_right_keypoints_2d"), label="right hand", expected_points=21)
    face = _triples(person.get("face_keypoints_2d"), label="face", expected_points=70)

    sharpness = _finite(observation.get("sharpness"), label="observation sharpness")
    occlusion = _finite(observation.get("occlusion"), label="observation occlusion")
    face_visibility = _finite(observation.get("face_visibility"), label="face visibility")
    full_body_visibility = _finite(observation.get("full_body_visibility"), label="full-body visibility")
    target_confidence = _finite(observation.get("target_confidence"), label="target confidence")
    view = str(observation.get("view") or "")

    claims: dict[str, list[dict[str, object]]] = {}

    # OpenPose face layout follows the common 68-point contour plus two pupil
    # points. Indices 36..47 are the two eye contours. Require both eyes, a
    # frontal source observation and enough real pixels for iris/eyelid detail.
    left_eye = _confident(face[36:42], threshold=0.25, width=frame_width, height=frame_height)
    right_eye = _confident(face[42:48], threshold=0.25, width=frame_width, height=frame_height)
    eye_points = [*left_eye, *right_eye]
    if (
        view == "front"
        and target_confidence >= 0.80
        and face_visibility >= 0.88
        and len(left_eye) >= 5
        and len(right_eye) >= 5
    ):
        eye_quality = _quality(
            confidence=min(_mean_confidence(left_eye), _mean_confidence(right_eye)),
            pixel_extent=_diagonal(eye_points),
            required_pixels=110.0,
            sharpness=sharpness,
            occlusion=occlusion,
        )
        claims["eyes_detail"] = [_claim(scene, eye_quality)]

    # Hand detail requires both hands to be independently observed. This avoids
    # allowing one good hand to stand in for the subject's other hand.
    left = _confident(left_hand, threshold=0.20, width=frame_width, height=frame_height)
    right = _confident(right_hand, threshold=0.20, width=frame_width, height=frame_height)
    if target_confidence >= 0.75 and full_body_visibility >= 0.72 and len(left) >= 16 and len(right) >= 16:
        hand_quality = _quality(
            confidence=min(_mean_confidence(left), _mean_confidence(right)),
            pixel_extent=min(_diagonal(left), _diagonal(right)),
            required_pixels=120.0,
            sharpness=sharpness,
            occlusion=occlusion,
        )
        claims["hands"] = [_claim(scene, hand_quality)]

    # BODY_25 indices 19..21 and 22..24 are left/right big toe, small toe and
    # heel. Require all three landmarks for each foot and a meaningful source
    # footprint. This proves foot visibility only; it does not prove toenails.
    left_foot = _confident(body[19:22], threshold=0.20, width=frame_width, height=frame_height)
    right_foot = _confident(body[22:25], threshold=0.20, width=frame_width, height=frame_height)
    if target_confidence >= 0.75 and full_body_visibility >= 0.82 and len(left_foot) == 3 and len(right_foot) == 3:
        foot_quality = _quality(
            confidence=min(_mean_confidence(left_foot), _mean_confidence(right_foot)),
            pixel_extent=min(_diagonal(left_foot), _diagonal(right_foot)),
            required_pixels=70.0,
            sharpness=sharpness,
            occlusion=occlusion,
        )
        claims["feet"] = [_claim(scene, foot_quality)]

    return claims


def merge_best_claims(
    destination: dict[str, list[dict[str, object]]],
    incoming: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    """Keep at most the strongest claim per domain/scene."""

    for domain, raw_claims in incoming.items():
        if domain not in {"eyes_detail", "hands", "feet"}:
            raise PhotoIdentityOpenPoseDetailError(f"unsupported OpenPose detail domain: {domain}")
        by_scene = {
            str(item["scene_id"]): dict(item)
            for item in destination.get(domain, [])
            if isinstance(item, Mapping) and item.get("scene_id")
        }
        for raw in raw_claims:
            claim = dict(raw)
            scene = str(claim.get("scene_id") or "")
            quality = _finite(claim.get("quality"), label=f"{domain} quality")
            current = by_scene.get(scene)
            if current is None or quality > float(current.get("quality", 0.0)):
                by_scene[scene] = claim
        destination[domain] = sorted(by_scene.values(), key=lambda item: (-float(item["quality"]), str(item["scene_id"])))
