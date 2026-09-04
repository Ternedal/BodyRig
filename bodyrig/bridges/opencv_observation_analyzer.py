#!/usr/bin/env python
"""Lightweight BodyRig observation analyzer for Stash source selection.

Runs out-of-process in the existing recovery Python environment. It intentionally
uses sparse OpenCV sampling instead of HMR2 so expensive recovery only sees the
small, high-value segments selected afterwards.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ADAPTER = "opencv-hog-haar"
REVISION = "1"
MAX_SAMPLES_PER_SOURCE = 400
BASE_SAMPLE_INTERVAL_SECONDS = 2.0
WINDOW_SECONDS = 6.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _area(box: tuple[int, int, int, int]) -> float:
    return float(max(0, box[2]) * max(0, box[3]))


def _intersection_fraction(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    denominator = _area(a)
    return float(overlap) / denominator if denominator > 0 else 0.0


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    overlap_fraction = _intersection_fraction(a, b)
    overlap = overlap_fraction * _area(a)
    union = _area(a) + _area(b) - overlap
    return overlap / union if union > 0 else 0.0


def _nms(rows: list[tuple[tuple[int, int, int, int], float]], threshold: float = 0.45) -> list[tuple[tuple[int, int, int, int], float]]:
    kept: list[tuple[tuple[int, int, int, int], float]] = []
    for row in sorted(rows, key=lambda item: (-item[1], -_area(item[0]))):
        if all(_iou(row[0], existing[0]) < threshold for existing in kept):
            kept.append(row)
    return kept


def _full_body_score(box: tuple[int, int, int, int], width: int, height: int) -> float:
    x, y, w, h = box
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return 0.0
    margins = [
        x / width,
        y / height,
        (width - (x + w)) / width,
        (height - (y + h)) / height,
    ]
    edge_score = sum(1.0 for value in margins if value >= 0.015) / 4.0
    height_fraction = h / height
    size_score = _clamp(height_fraction / 0.45)
    if height_fraction > 0.97:
        edge_score *= 0.35
    return _clamp(edge_score * size_score)


def _face_score(face: tuple[int, int, int, int] | None, person: tuple[int, int, int, int] | None) -> float:
    if face is None:
        return 0.0
    denominator = _area(person) if person is not None else 0.0
    if denominator <= 0.0:
        denominator = _area(face) * 8.0
    ratio = _area(face) / max(denominator, 1.0)
    return _clamp(0.48 + ratio * 7.0)


def _sharpness(cv2: Any, image: Any) -> float:
    if image is None or getattr(image, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if not math.isfinite(variance) or variance <= 0:
        return 0.0
    return _clamp(1.0 - math.exp(-variance / 160.0))


def _largest_face(cascade: Any, gray: Any) -> tuple[int, int, int, int] | None:
    rows = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4, minSize=(24, 24))
    if len(rows) == 0:
        return None
    return max((tuple(int(value) for value in row) for row in rows), key=_area)


def _face_and_view(cv2: Any, front: Any, profile: Any, crop: Any) -> tuple[tuple[int, int, int, int] | None, str]:
    if crop is None or getattr(crop, "size", 0) == 0:
        return None, "unknown"
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    face = _largest_face(front, gray)
    if face is not None:
        return face, "front"
    face = _largest_face(profile, gray)
    if face is not None:
        return face, "left_profile"
    flipped = cv2.flip(gray, 1)
    face = _largest_face(profile, flipped)
    if face is not None:
        return face, "right_profile"
    return None, "unknown"


def _read_manifest_counts(path: Path, expected_performer_id: str) -> list[int]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("could not read Stash source manifest") from exc
    if manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise RuntimeError("unsupported Stash source manifest")
    performer = manifest.get("performer") or {}
    if str(performer.get("id") or "") != expected_performer_id:
        raise RuntimeError("Stash source manifest performer does not match analyzer request")
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 10:
        raise RuntimeError("Stash source manifest selected must contain 1..10 entries")
    counts: list[int] = []
    for item in selected:
        try:
            count = int(item["performer_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Stash source manifest performer_count is invalid") from exc
        if count < 1:
            raise RuntimeError("Stash source manifest performer_count must be positive")
        counts.append(count)
    return counts


def _analyze_source(
    cv2: Any,
    *,
    path: Path,
    source_id: str,
    requested_duration: float,
    performer_count: int,
    hog: Any,
    front: Any,
    profile: Any,
) -> list[dict[str, Any]]:
    # This lightweight adapter cannot visually disambiguate a named Stash
    # performer from another person. Multi-performer footage is therefore left
    # to a future identity-aware analyzer rather than silently picking a person.
    if performer_count != 1:
        return []

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return []
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        actual_duration = frame_count / fps if fps > 0 and frame_count > 0 else requested_duration
        duration = min(requested_duration, actual_duration) if actual_duration > 0 else requested_duration
        if not math.isfinite(duration) or duration < 1.0:
            return []
        interval = max(BASE_SAMPLE_INTERVAL_SECONDS, duration / MAX_SAMPLES_PER_SOURCE)
        timestamp = min(1.0, duration / 2.0)
        rows: list[dict[str, Any]] = []
        previous_center: tuple[float, float] | None = None
        previous_time: float | None = None

        while timestamp < duration and len(rows) < MAX_SAMPLES_PER_SOURCE:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                timestamp += interval
                continue
            original_height, original_width = frame.shape[:2]
            if original_width <= 0 or original_height <= 0:
                timestamp += interval
                continue
            scale = min(1.0, 640.0 / max(original_width, original_height))
            small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
            height, width = small.shape[:2]

            rects, weights = hog.detectMultiScale(
                small,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
            detections = _nms([
                (tuple(int(value) for value in rect), float(weights[index]) if index < len(weights) else 0.0)
                for index, rect in enumerate(rects)
            ])

            target: tuple[int, int, int, int] | None = None
            detector_weight = 0.0
            other_boxes: list[tuple[int, int, int, int]] = []
            if detections:
                target, detector_weight = max(detections, key=lambda item: _area(item[0]))
                other_boxes = [item[0] for item in detections if item[0] != target]
                x, y, w, h = target
                x = max(0, min(x, width - 1))
                y = max(0, min(y, height - 1))
                w = max(1, min(w, width - x))
                h = max(1, min(h, height - y))
                target = (x, y, w, h)
                crop = small[y:y+h, x:x+w]
                face, view = _face_and_view(cv2, front, profile, crop)
                face_visibility = _face_score(face, target)
                screen_fraction = _clamp(_area(target) / float(width * height))
                full_body = _full_body_score(target, width, height)
                sharpness = _sharpness(cv2, crop)
                occlusion = max((_intersection_fraction(target, box) for box in other_boxes), default=0.0)
                confidence = _clamp(0.48 + 0.28 * (1.0 - math.exp(-max(0.0, detector_weight))) + 0.20 * (1.0 if face is not None else 0.0))
                center = (x + w / 2.0, y + h / 2.0)
                if previous_center is not None and previous_time is not None and timestamp > previous_time:
                    distance = math.hypot(center[0] - previous_center[0], center[1] - previous_center[1])
                    motion = _clamp((distance / max(float(h), 1.0)) / (timestamp - previous_time) * 2.5)
                else:
                    motion = 0.15
                previous_center = center
                previous_time = timestamp
            else:
                # Face-only observations still help identity fitting when HOG
                # misses a seated/close person. They intentionally score poorly
                # for full-body recovery.
                face, view = _face_and_view(cv2, front, profile, small)
                if face is None:
                    timestamp += interval
                    continue
                x, y, w, h = face
                crop = small[y:y+h, x:x+w]
                face_visibility = _face_score(face, None)
                screen_fraction = _clamp((_area(face) / float(width * height)) * 5.0)
                full_body = 0.0
                sharpness = _sharpness(cv2, crop)
                occlusion = 0.0
                confidence = 0.60
                motion = 0.05

            start = max(0.0, min(timestamp - WINDOW_SECONDS / 2.0, max(0.0, duration - 1.0)))
            window_duration = min(WINDOW_SECONDS, duration - start)
            if window_duration >= 1.0:
                rows.append({
                    "source_id": source_id,
                    "start_seconds": round(start, 3),
                    "duration_seconds": round(window_duration, 3),
                    "target_confidence": round(confidence, 4),
                    "target_screen_fraction": round(screen_fraction, 4),
                    "face_visibility": round(face_visibility, 4),
                    "full_body_visibility": round(full_body, 4),
                    "sharpness": round(sharpness, 4),
                    "occlusion": round(_clamp(occlusion), 4),
                    "motion": round(motion, 4),
                    "view": view,
                })
            timestamp += interval
        return rows
    finally:
        capture.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bodyrig-stash-manifest", required=True)
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-source-id", action="append", default=[])
    parser.add_argument("--bodyrig-source-path", action="append", default=[])
    args = parser.parse_args()

    try:
        if args.bodyrig_adapter != ADAPTER or args.bodyrig_revision != REVISION:
            raise RuntimeError("OpenCV observation adapter/revision mismatch")
        request_path = Path(args.bodyrig_request).resolve()
        output = Path(args.bodyrig_output).resolve()
        workspace = Path(args.bodyrig_workspace).resolve()
        if not request_path.is_file() or not output.is_dir() or not workspace.is_dir():
            raise RuntimeError("BodyRig analyzer request/output/workspace boundary is invalid")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or request.get("format") != "bodyrig-observation-analyzer-request" or request.get("version") != 1:
            raise RuntimeError("unsupported BodyRig observation request")
        performer_id = str(request.get("performer_id") or "")
        request_sources = request.get("sources")
        if not isinstance(request_sources, list) or len(request_sources) != len(args.bodyrig_source_id):
            raise RuntimeError("BodyRig observation source mapping is inconsistent")
        if len(args.bodyrig_source_id) != len(args.bodyrig_source_path) or not 1 <= len(args.bodyrig_source_id) <= 10:
            raise RuntimeError("BodyRig observation source arguments are inconsistent")
        expected_ids = [str(item.get("source_id") or "") for item in request_sources]
        if expected_ids != args.bodyrig_source_id:
            raise RuntimeError("BodyRig observation source id order mismatch")
        performer_counts = _read_manifest_counts(Path(args.bodyrig_stash_manifest).resolve(), performer_id)
        if len(performer_counts) != len(expected_ids):
            raise RuntimeError("Stash manifest/source count mismatch")

        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv/cv2 is required for the built-in observation analyzer") from exc

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        front_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        profile_path = Path(cv2.data.haarcascades) / "haarcascade_profileface.xml"
        front = cv2.CascadeClassifier(str(front_path))
        profile = cv2.CascadeClassifier(str(profile_path))
        if front.empty() or profile.empty():
            raise RuntimeError("OpenCV Haar cascades are unavailable")

        observations: list[dict[str, Any]] = []
        for index, source_row in enumerate(request_sources):
            source_path = Path(args.bodyrig_source_path[index]).expanduser().resolve()
            if not source_path.is_file():
                raise RuntimeError(f"BodyRig observation source is not a file: {source_path}")
            observations.extend(
                _analyze_source(
                    cv2,
                    path=source_path,
                    source_id=expected_ids[index],
                    requested_duration=float(source_row["duration"]),
                    performer_count=performer_counts[index],
                    hog=hog,
                    front=front,
                    profile=profile,
                )
            )
        if not observations:
            raise RuntimeError("OpenCV observation analyzer found no usable single-performer observation")
        result = {
            "format": "bodyrig-observation-analyzer-result",
            "version": 1,
            "adapter": ADAPTER,
            "revision": REVISION,
            "observations": observations,
        }
        target = output / "observations.json"
        target.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        print(f"BodyRig OpenCV observation analyzer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
