from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

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


def _dimensions(frame_width: Any, frame_height: Any) -> tuple[int, int]:
    if (
        isinstance(frame_width, bool)
        or isinstance(frame_height, bool)
        or not isinstance(frame_width, int)
        or not isinstance(frame_height, int)
        or frame_width < 1
        or frame_height < 1
    ):
        raise PhotoIdentityNailLandmarkError("source frame dimensions are invalid")
    return frame_width, frame_height


def _crop_px(
    crop: Sequence[Any],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    if isinstance(crop, (str, bytes)) or not isinstance(crop, Sequence) or len(crop) != 4:
        raise PhotoIdentityNailLandmarkError("nail landmark crop must contain left,top,right,bottom")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in crop):
        raise PhotoIdentityNailLandmarkError("nail landmark crop must use integer source pixels")
    left, top, right, bottom = [int(item) for item in crop]
    if left < 0 or top < 0 or right <= left or bottom <= top or right > frame_width or bottom > frame_height:
        raise PhotoIdentityNailLandmarkError("nail landmark crop escaped source frame bounds")
    return left, top, right, bottom


def normalized_crop_to_pixels(
    crop_norm: Sequence[Any],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    width, height = _dimensions(frame_width, frame_height)
    if isinstance(crop_norm, (str, bytes)) or not isinstance(crop_norm, Sequence) or len(crop_norm) != 4:
        raise PhotoIdentityNailLandmarkError("normalized nail crop must contain x,y,width,height")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in crop_norm):
        raise PhotoIdentityNailLandmarkError("normalized nail crop contains a non-numeric value")
    x, y, crop_width, crop_height = [float(item) for item in crop_norm]
    if not all(math.isfinite(item) for item in (x, y, crop_width, crop_height)):
        raise PhotoIdentityNailLandmarkError("normalized nail crop contains a non-finite value")
    if x < 0.0 or y < 0.0 or crop_width <= 0.0 or crop_height <= 0.0 or x + crop_width > 1.0 or y + crop_height > 1.0:
        raise PhotoIdentityNailLandmarkError("normalized nail crop escaped source frame bounds")

    left = int(round(x * width))
    top = int(round(y * height))
    pixel_width = max(1, int(round(crop_width * width)))
    pixel_height = max(1, int(round(crop_height * height)))
    if left >= width or top >= height:
        raise PhotoIdentityNailLandmarkError("normalized nail crop starts outside source frame")
    right = min(width, left + pixel_width)
    bottom = min(height, top + pixel_height)
    return _crop_px((left, top, right, bottom), frame_width=width, frame_height=height)


def _point_in_crop(point: tuple[float, float, float], crop: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = crop
    return left <= point[0] < right and top <= point[1] < bottom


def _canvas_point(
    point: tuple[float, float, float],
    *,
    crop: tuple[int, int, int, int],
    upscale_to_canvas: bool = False,
) -> dict[str, float]:
    left, top, right, bottom = crop
    width = right - left
    height = bottom - top
    if width < 1 or height < 1:
        raise PhotoIdentityNailLandmarkError("nail landmark crop is empty")
    scale = min(CANVAS_SIZE / float(width), CANVAS_SIZE / float(height))
    if not upscale_to_canvas:
        scale = min(1.0, scale)
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
    crop: tuple[int, int, int, int] | None = None,
    upscale_to_canvas: bool = False,
) -> dict[str, Any]:
    key = "hand_left_keypoints_2d" if side == "left" else "hand_right_keypoints_2d"
    hand = _triples(person.get(key), label=f"{side} hand", expected=21)
    confident = _in_frame(hand, threshold=HAND_POINT_THRESHOLD, width=frame_width, height=frame_height)
    if len(confident) < MIN_HAND_CONFIDENT_POINTS:
        raise PhotoIdentityNailLandmarkError(f"{side} hand lacks enough confident OpenPose points")
    selected_crop = crop or _square_crop(
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
            and _point_in_crop(point, selected_crop)
        ):
            landmarks[label] = _canvas_point(
                point,
                crop=selected_crop,
                upscale_to_canvas=upscale_to_canvas,
            )
    return {
        "source_crop_px": list(selected_crop),
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
    crop: tuple[int, int, int, int] | None = None,
    upscale_to_canvas: bool = False,
) -> dict[str, Any]:
    body = _triples(person.get("pose_keypoints_2d"), label="BODY_25", expected=25)
    indices = (19, 20, 21) if side == "left" else (22, 23, 24)
    points = [body[index] for index in indices]
    confident = _in_frame(points, threshold=FOOT_POINT_THRESHOLD, width=frame_width, height=frame_height)
    if len(confident) != 3:
        raise PhotoIdentityNailLandmarkError(f"{side} foot lacks big-toe/small-toe/heel OpenPose landmarks")
    selected_crop = crop or _square_crop(
        confident,
        width=frame_width,
        height=frame_height,
        padding=0.45,
        minimum_side=max(96, MIN_FOOT_NATIVE_CROP // 2),
    )
    landmarks = {
        label: _canvas_point(point, crop=selected_crop, upscale_to_canvas=upscale_to_canvas)
        for label, point in zip(TOE_LABELS, points)
        if _point_in_crop(point, selected_crop)
    }
    return {
        "source_crop_px": list(selected_crop),
        "landmarks": landmarks,
        "required_landmark_count": len(TOE_LABELS),
        "observed_landmark_count": len(landmarks),
        "application_ready": len(landmarks) == len(TOE_LABELS),
    }


def _project(
    payload: Mapping[str, Any],
    *,
    region: str,
    frame_width: int,
    frame_height: int,
    crop: tuple[int, int, int, int] | None,
    upscale_to_canvas: bool,
    source_coordinate_authority: str,
) -> dict[str, Any]:
    if region not in REGIONS:
        raise PhotoIdentityNailLandmarkError("nail landmark region is not canonical")
    width, height = _dimensions(frame_width, frame_height)
    selected_crop = None if crop is None else _crop_px(crop, frame_width=width, frame_height=height)
    person = _person(payload)
    side = "left" if region.startswith("left_") else "right"
    if region.endswith("fingernails"):
        projection = _hand_projection(
            person,
            side=side,
            frame_width=width,
            frame_height=height,
            crop=selected_crop,
            upscale_to_canvas=upscale_to_canvas,
        )
    else:
        projection = _foot_projection(
            person,
            side=side,
            frame_width=width,
            frame_height=height,
            crop=selected_crop,
            upscale_to_canvas=upscale_to_canvas,
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "region": region,
        "canvas_width": CANVAS_SIZE,
        "canvas_height": CANVAS_SIZE,
        **projection,
        "source_coordinate_authority": source_coordinate_authority,
        "package_application_authority": False,
        "human_review_required": True,
        "production_activation": False,
    }


def project_nail_landmarks(
    payload: Mapping[str, Any],
    *,
    region: str,
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    return _project(
        payload,
        region=region,
        frame_width=frame_width,
        frame_height=frame_height,
        crop=None,
        upscale_to_canvas=False,
        source_coordinate_authority="openpose-semantic-landmarks",
    )


def project_nail_landmarks_to_crop(
    payload: Mapping[str, Any],
    *,
    region: str,
    frame_width: int,
    frame_height: int,
    crop_px: Sequence[Any],
    upscale_to_canvas: bool = True,
) -> dict[str, Any]:
    width, height = _dimensions(frame_width, frame_height)
    crop = _crop_px(crop_px, frame_width=width, frame_height=height)
    return _project(
        payload,
        region=region,
        frame_width=width,
        frame_height=height,
        crop=crop,
        upscale_to_canvas=bool(upscale_to_canvas),
        source_coordinate_authority="openpose-semantic-landmarks-explicit-crop",
    )
