from __future__ import annotations

from typing import Any, Mapping

from .photoidentity_nail_source_discovery import (
    FOOT_POINT_THRESHOLD,
    HAND_POINT_THRESHOLD,
    HAND_TIP_INDICES,
    HAND_TIP_THRESHOLD,
    MIN_FOOT_NATIVE_CROP,
    MIN_HAND_CONFIDENT_POINTS,
    MIN_HAND_NATIVE_CROP,
    _in_frame,
    _square_crop,
    _triples,
)

FORMAT = "bodyrig-photoidentity-nail-landmark-projection"
VERSION = 1
POLICY_REVISION = "photoidentity-nail-landmark-projection-v1"
CANVAS_SIZE = 1024
HAND_LABELS = ("thumb", "index", "middle", "ring", "pinky")
TOE_LABELS = ("big_toe", "small_toe", "heel")
REGIONS = ("left_fingernails", "right_fingernails", "left_toenails", "right_toenails")


class PhotoIdentityNailLandmarkError(RuntimeError):
    pass


def _person(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    people = payload.get("people")
    if not isinstance(people, list) or len(people) != 1 or not isinstance(people[0], Mapping):
        raise PhotoIdentityNailLandmarkError("nail landmark projection requires exactly one OpenPose person")
    return people[0]


def _canvas_point(
    point: tuple[float, float, float],
    *,
    crop: tuple[int, int, int, int],
) -> dict[str, float]:
    left, top, right, bottom = crop
    width = right - left
    height = bottom - top
    if width < 1 or height < 1:
        raise PhotoIdentityNailLandmarkError("nail landmark crop is empty")
    rendered_width = min(width, CANVAS_SIZE)
    rendered_height = min(height, CANVAS_SIZE)
    scale = min(rendered_width / float(width), rendered_height / float(height))
    actual_width = width * scale
    actual_height = height * scale
    offset_x = (CANVAS_SIZE - actual_width) / 2.0
    offset_y = (CANVAS_SIZE - actual_height) / 2.0
    x = offset_x + (point[0] - left) * scale
    y = offset_y + (point[1] - top) * scale
    if not 0.0 <= x <= CANVAS_SIZE or not 0.0 <= y <= CANVAS_SIZE:
        raise PhotoIdentityNailLandmarkError("projected nail landmark escaped canonical closeup canvas")
    return {
        "x_norm": round(x / CANVAS_SIZE, 8),
        "y_norm": round(y / CANVAS_SIZE, 8),
        "confidence": round(float(point[2]), 6),
    }


def _hand_projection(
    person: Mapping[str, Any],
    *,
    side: str,
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    key = "hand_left_keypoints_2d" if side == "left" else "hand_right_keypoints_2d"
    hand = _triples(person.get(key), label=f"{side} hand", expected=21)
    confident = _in_frame(
        hand,
        threshold=HAND_POINT_THRESHOLD,
        width=frame_width,
        height=frame_height,
    )
    if len(confident) < MIN_HAND_CONFIDENT_POINTS:
        raise PhotoIdentityNailLandmarkError(f"{side} hand lacks enough confident OpenPose points")
    crop = _square_crop(
        confident,
        width=frame_width,
        height=frame_height,
        padding=0.45,
        minimum_side=max(96, MIN_HAND_NATIVE_CROP // 2),
    )
    landmarks: dict[str, dict[str, float]] = {}
    for label, index in zip(HAND_LABELS, HAND_TIP_INDICES):
        point = hand[index]
        if (
            point[2] >= HAND_TIP_THRESHOLD
            and 0.0 <= point[0] < frame_width
            and 0.0 <= point[1] < frame_height
        ):
            landmarks[label] = _canvas_point(point, crop=crop)
    return {
        "source_crop_px": list(crop),
        "landmarks": landmarks,
        "required_landmark_count": len(HAND_LABELS),
        "observed_landmark_count": len(landmarks),
        "application_ready": len(landmarks) == len(HAND_LABELS),
    }


def _foot_projection(
    person: Mapping[str, Any],
    *,
    side: str,
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected=25)
    indices = (19, 20, 21) if side == "left" else (22, 23, 24)
    points = [body[index] for index in indices]
    confident = _in_frame(
        points,
        threshold=FOOT_POINT_THRESHOLD,
        width=frame_width,
        height=frame_height,
    )
    if len(confident) != 3:
        raise PhotoIdentityNailLandmarkError(f"{side} foot lacks big-toe/small-toe/heel OpenPose landmarks")
    crop = _square_crop(
        confident,
        width=frame_width,
        height=frame_height,
        padding=0.45,
        minimum_side=max(96, MIN_FOOT_NATIVE_CROP // 2),
    )
    landmarks = {
        label: _canvas_point(point, crop=crop)
        for label, point in zip(TOE_LABELS, points)
    }
    return {
        "source_crop_px": list(crop),
        "landmarks": landmarks,
        "required_landmark_count": len(TOE_LABELS),
        "observed_landmark_count": len(landmarks),
        "application_ready": True,
    }


def project_nail_landmarks(
    payload: Mapping[str, Any],
    *,
    region: str,
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    if region not in REGIONS:
        raise PhotoIdentityNailLandmarkError("nail landmark region is not canonical")
    if (
        isinstance(frame_width, bool)
        or isinstance(frame_height, bool)
        or not isinstance(frame_width, int)
        or not isinstance(frame_height, int)
        or frame_width < 1
        or frame_height < 1
    ):
        raise PhotoIdentityNailLandmarkError("source frame dimensions are invalid")
    person = _person(payload)
    side = "left" if region.startswith("left_") else "right"
    if region.endswith("fingernails"):
        projection = _hand_projection(
            person,
            side=side,
            frame_width=frame_width,
            frame_height=frame_height,
        )
    else:
        projection = _foot_projection(
            person,
            side=side,
            frame_width=frame_width,
            frame_height=frame_height,
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "region": region,
        "canvas_width": CANVAS_SIZE,
        "canvas_height": CANVAS_SIZE,
        **projection,
        "source_coordinate_authority": "openpose-semantic-landmarks",
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }
