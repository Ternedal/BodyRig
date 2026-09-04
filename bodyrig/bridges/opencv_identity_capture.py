#!/usr/bin/env python
"""Built-in BodyRig visual identity capture from already-selected video segments.

This is a standalone adapter: it deliberately has no BodyRig package imports so
it can run in the pinned external recovery Python environment. Source media and
extracted frames stay in the private workspace. The result directory receives
only the strict metadata-only identity.json accepted by BodyRig core.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ADAPTER = "opencv-identity-rgba"
REVISION = "1"
SAMPLE_INTERVAL_SECONDS = 0.75
MAX_SAMPLES_PER_SOURCE = 40


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _area(box: tuple[int, int, int, int]) -> float:
    return float(max(0, box[2]) * max(0, box[3]))


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    union = _area(a) + _area(b) - overlap
    return overlap / union if union > 0 else 0.0


def _nms(rows: list[tuple[tuple[int, int, int, int], float]], threshold: float = 0.45):
    kept: list[tuple[tuple[int, int, int, int], float]] = []
    for row in sorted(rows, key=lambda item: (-item[1], -_area(item[0]))):
        if all(_iou(row[0], prior[0]) < threshold for prior in kept):
            kept.append(row)
    return kept


def _framing_score(box: tuple[int, int, int, int], width: int, height: int) -> float:
    x, y, w, h = box
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return 0.0
    height_fraction = h / height
    width_fraction = w / width
    margins = (x / width, y / height, (width - x - w) / width, (height - y - h) / height)
    visible_edges = sum(1 for margin in margins if margin >= 0.0125) / 4.0
    useful_height = _clamp(height_fraction / 0.50)
    oversize_penalty = 0.45 if height_fraction > 0.97 or width_fraction > 0.96 else 1.0
    return _clamp(visible_edges * useful_height * oversize_penalty)


def _sharpness_score(variance: float) -> float:
    if not math.isfinite(variance) or variance <= 0:
        return 0.0
    return _clamp(1.0 - math.exp(-variance / 180.0))


def _lighting_score(mean_luma: float, std_luma: float) -> float:
    # Prefer a non-clipped midtone image with some local contrast. This is only
    # a capture-quality indicator; it does not alter the source image.
    mean = _clamp(mean_luma / 255.0)
    contrast = _clamp(std_luma / 64.0)
    exposure = _clamp(1.0 - abs(mean - 0.50) / 0.50)
    return _clamp(0.68 * exposure + 0.32 * contrast)


def _candidate_score(*, framing: float, face: bool, sharpness: float, lighting: float, detector: float) -> float:
    return _clamp(
        0.34 * framing
        + 0.19 * (1.0 if face else 0.0)
        + 0.21 * sharpness
        + 0.13 * lighting
        + 0.13 * detector
    )


def _coverage_profile(*, observed: int, face_frames: int, full_body_frames: int, side_frames: int) -> dict[str, float]:
    if observed < 1:
        raise ValueError("observed must be positive")
    face = _clamp(face_frames / max(3.0, observed * 0.20))
    body = _clamp(full_body_frames / max(3.0, observed * 0.20))
    side = _clamp(side_frames / max(2.0, observed * 0.10))
    return {
        "face": face,
        "hair_or_scalp": face,
        "skin": _clamp(face * 0.85),
        "clothing": body,
        "full_body": body,
        "back": 0.0,
        "side": side,
    }


def _detect_faces(cv2: Any, front: Any, profile: Any, crop: Any) -> tuple[bool, bool]:
    if crop is None or getattr(crop, "size", 0) == 0:
        return False, False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    frontal = front.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4, minSize=(24, 24))
    if len(frontal):
        return True, False
    side = profile.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4, minSize=(24, 24))
    if len(side):
        return True, True
    flipped = cv2.flip(gray, 1)
    side = profile.detectMultiScale(flipped, scaleFactor=1.12, minNeighbors=4, minSize=(24, 24))
    return (len(side) > 0, len(side) > 0)


def _grabcut_rgba(cv2: Any, np: Any, frame: Any, box: tuple[int, int, int, int]):
    height, width = frame.shape[:2]
    x, y, w, h = box
    pad_x = max(3, int(w * 0.08))
    pad_y = max(3, int(h * 0.04))
    left = max(1, x - pad_x)
    top = max(1, y - pad_y)
    right = min(width - 1, x + w + pad_x)
    bottom = min(height - 1, y + h + pad_y)
    rect = (left, top, max(2, right - left), max(2, bottom - top))
    mask = np.zeros((height, width), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(frame, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    kernel = np.ones((3, 3), np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel)
    fraction = float((foreground > 0).sum()) / float(width * height)
    if not 0.03 <= fraction <= 0.90:
        raise RuntimeError("GrabCut foreground fraction is implausible")
    rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = foreground
    return rgba, fraction


def _read_request(path: Path, adapter: str, revision: str) -> dict[str, Any]:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("identity capture request is invalid JSON") from exc
    required = {"format", "version", "adapter", "revision", "source_count", "subject_track_id", "observed_frames"}
    if not isinstance(request, dict) or set(request) != required:
        raise RuntimeError("identity capture request fields do not match v1")
    if request["format"] != "bodyrig-identity-capture-request" or request["version"] != 1:
        raise RuntimeError("unsupported identity capture request")
    if request["adapter"] != adapter or request["revision"] != revision:
        raise RuntimeError("identity capture adapter/revision mismatch")
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bodyrig-request", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--bodyrig-output", required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-source", action="append", default=[])
    args = parser.parse_args()

    try:
        if args.bodyrig_adapter != ADAPTER or args.bodyrig_revision != REVISION:
            raise RuntimeError("built-in identity capture adapter/revision mismatch")
        request_path = Path(args.bodyrig_request).resolve()
        workspace = Path(args.bodyrig_workspace).resolve()
        output = Path(args.bodyrig_output).resolve()
        if not request_path.is_file() or not workspace.is_dir() or not output.is_dir():
            raise RuntimeError("BodyRig identity capture boundary paths are invalid")
        request = _read_request(request_path, args.bodyrig_adapter, args.bodyrig_revision)
        sources = [Path(value).expanduser().resolve() for value in args.bodyrig_source]
        if len(sources) != request["source_count"] or not 1 <= len(sources) <= 10:
            raise RuntimeError("identity capture source count mismatch")
        if any(not path.is_file() for path in sources):
            raise RuntimeError("identity capture source is not a file")

        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("opencv/cv2 and numpy are required for built-in identity capture") from exc

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        front = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        profile = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_profileface.xml"))
        if front.empty() or profile.empty():
            raise RuntimeError("OpenCV Haar cascades are unavailable")

        observed = 0
        face_frames = 0
        side_frames = 0
        full_body_frames = 0
        sharpness_values: list[float] = []
        lighting_values: list[float] = []
        visibility_values: list[float] = []
        best: tuple[float, Any, tuple[int, int, int, int], dict[str, Any]] | None = None

        for source_index, source in enumerate(sources):
            capture = cv2.VideoCapture(str(source))
            try:
                if not capture.isOpened():
                    continue
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
                duration = frames / fps if fps > 0 and frames > 0 else 0.0
                if duration <= 0:
                    duration = 12.0
                timestamp = min(0.4, duration / 2.0)
                samples = 0
                while timestamp < duration and samples < MAX_SAMPLES_PER_SOURCE:
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        timestamp += SAMPLE_INTERVAL_SECONDS
                        continue
                    samples += 1
                    observed += 1
                    original = frame
                    height0, width0 = original.shape[:2]
                    scale = min(1.0, 720.0 / max(width0, height0))
                    small = cv2.resize(original, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else original
                    height, width = small.shape[:2]
                    rects, weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
                    detections = _nms([
                        (tuple(int(v) for v in rect), float(weights[i]) if i < len(weights) else 0.0)
                        for i, rect in enumerate(rects)
                    ])
                    if len(detections) != 1:
                        timestamp += SAMPLE_INTERVAL_SECONDS
                        continue
                    box, detector_weight = detections[0]
                    x, y, w, h = box
                    x, y = max(0, x), max(0, y)
                    w, h = min(w, width - x), min(h, height - y)
                    if w <= 0 or h <= 0:
                        timestamp += SAMPLE_INTERVAL_SECONDS
                        continue
                    box = (x, y, w, h)
                    crop = small[y:y+h, x:x+w]
                    has_face, is_side = _detect_faces(cv2, front, profile, crop)
                    if has_face:
                        face_frames += 1
                    if is_side:
                        side_frames += 1
                    framing = _framing_score(box, width, height)
                    if framing >= 0.72:
                        full_body_frames += 1
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    sharpness = _sharpness_score(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                    lighting = _lighting_score(float(gray.mean()), float(gray.std()))
                    detector = _clamp(1.0 - math.exp(-max(0.0, detector_weight)))
                    visibility = _clamp(0.65 * framing + 0.35 * detector)
                    sharpness_values.append(sharpness)
                    lighting_values.append(lighting)
                    visibility_values.append(visibility)
                    score = _candidate_score(
                        framing=framing,
                        face=has_face,
                        sharpness=sharpness,
                        lighting=lighting,
                        detector=detector,
                    )
                    if has_face and framing >= 0.55 and (best is None or score > best[0]):
                        # Convert detector coordinates back to original image.
                        inverse = 1.0 / scale
                        original_box = (
                            int(x * inverse), int(y * inverse),
                            int(w * inverse), int(h * inverse),
                        )
                        best = (score, original.copy(), original_box, {
                            "source_index": source_index,
                            "time_seconds": round(timestamp, 3),
                            "sharpness": sharpness,
                            "lighting": lighting,
                            "visibility": visibility,
                        })
                    timestamp += SAMPLE_INTERVAL_SECONDS
            finally:
                capture.release()

        if observed < 1 or best is None:
            raise RuntimeError("built-in identity capture found no usable single-person full-body frame with visible face")

        best_score, best_frame, best_box, best_meta = best
        rgba, foreground_fraction = _grabcut_rgba(cv2, np, best_frame, best_box)
        capture_dir = workspace / "identity-capture"
        capture_dir.mkdir(parents=True, exist_ok=False)
        rgba_path = capture_dir / "primary-rgba.png"
        rgb_path = capture_dir / "primary-rgb.png"
        if not cv2.imwrite(str(rgba_path), rgba) or not cv2.imwrite(str(rgb_path), best_frame):
            raise RuntimeError("failed to write private identity capture images")

        private_manifest = {
            "format": "bodyrig-private-identity-capture",
            "version": 1,
            "adapter": ADAPTER,
            "revision": REVISION,
            "subject_track_id": request["subject_track_id"],
            "primary": {
                "rgb": rgb_path.name,
                "rgba": rgba_path.name,
                "rgb_sha256": hashlib.sha256(rgb_path.read_bytes()).hexdigest(),
                "rgba_sha256": hashlib.sha256(rgba_path.read_bytes()).hexdigest(),
                "source_index": best_meta["source_index"],
                "time_seconds": best_meta["time_seconds"],
                "foreground_fraction": round(foreground_fraction, 4),
            },
        }
        (capture_dir / "capture.json").write_text(
            json.dumps(private_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        coverage = _coverage_profile(
            observed=observed,
            face_frames=face_frames,
            full_body_frames=full_body_frames,
            side_frames=side_frames,
        )
        identity = {
            "format": "bodyrig-visual-identity",
            "version": 1,
            "adapter": ADAPTER,
            "revision": REVISION,
            "source_count": request["source_count"],
            "subject_track_id": request["subject_track_id"],
            "capture": {
                "observed_frames": observed,
                "face_frames": face_frames,
                "full_body_frames": full_body_frames,
                "side_body_frames": side_frames,
                "rear_body_frames": 0,
            },
            "coverage": {
                "face": coverage["face"],
                "hair_or_scalp": coverage["hair_or_scalp"],
                "skin": coverage["skin"],
                "clothing": coverage["clothing"],
                "full_body": coverage["full_body"],
                "back": coverage["back"],
            },
            "quality": {
                "sharpness": round(sum(sharpness_values) / max(1, len(sharpness_values)), 4),
                "lighting": round(sum(lighting_values) / max(1, len(lighting_values)), 4),
                "visibility": round(sum(visibility_values) / max(1, len(visibility_values)), 4),
            },
            "privacy": {
                "contains_source_media": False,
                "contains_biometric_template": False,
            },
        }
        (output / "identity.json").write_text(
            json.dumps(identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"BodyRig built-in identity capture: PASS | score={best_score:.3f} | samples={observed}")
        return 0
    except Exception as exc:
        print(f"BodyRig built-in identity capture: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
