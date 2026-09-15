from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ADAPTER = "bodyrig-motion-reference-materializer-v1"
REQUEST_FORMAT = "bodyrig-photoreal-motion-reference-materialization-request"
RESULT_FORMAT = "bodyrig-photoreal-motion-reference-materialization-result"
VERSION = 1
MAX_FRAMES_PER_WINDOW = 300


class MotionReferenceMaterializerError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MotionReferenceMaterializerError(f"request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MotionReferenceMaterializerError("request must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    return clean


def _v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value != 1:
        raise MotionReferenceMaterializerError("request version must be numeric v1")


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise MotionReferenceMaterializerError(f"{label} is invalid")
    return round(result, 6)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _self_revision() -> str:
    return _file_sha(Path(__file__).resolve())


def _frame_sha(image: Any) -> str:
    contiguous = image if getattr(image, "flags", None) is not None and image.flags.c_contiguous else image.copy(order="C")
    digest = hashlib.sha256()
    digest.update(("x".join(str(int(value)) for value in contiguous.shape) + "\n").encode("ascii"))
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def _split_eye(np: Any, image: Any, *, layout: str, eye: str) -> Any:
    height, width = image.shape[:2]
    if layout == "side-by-side":
        midpoint = width // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise MotionReferenceMaterializerError("invalid side-by-side motion sample")
        image = image[:, :midpoint] if eye == "left" else image[:, midpoint:]
    elif layout == "over-under":
        midpoint = height // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise MotionReferenceMaterializerError("invalid over-under motion sample")
        image = image[:midpoint, :] if eye == "left" else image[midpoint:, :]
    elif layout == "mono":
        if eye != "mono":
            raise MotionReferenceMaterializerError("mono motion source requested non-mono eye")
    else:
        raise MotionReferenceMaterializerError(f"unsupported stereo layout: {layout}")
    if image.size == 0:
        raise MotionReferenceMaterializerError("decoded motion frame is empty")
    return np.ascontiguousarray(image)


def _decode_at(cv2: Any, np: Any, capture: Any, *, timestamp: float, layout: str, eye: str) -> Any:
    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
    ok, image = capture.read()
    if not ok or image is None:
        raise MotionReferenceMaterializerError(f"could not decode held-out video frame at {timestamp}s")
    return _split_eye(np, image, layout=layout, eye=eye)


def _validate_request(value: Mapping[str, Any], args: argparse.Namespace) -> None:
    required = {
        "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
        "animated_review_plan_sha256", "adapter", "revision", "sample_fps", "sources",
        "source_count", "window_count", "decode_semantics", "frame_hash_semantics",
        "teacher_process_disclosure", "build_only", "runtime_dependency",
        "animated_teacher_acceptance_authority", "p3_device_distillation_authorized",
        "production_activation",
    }
    if set(value) != required:
        raise MotionReferenceMaterializerError("request fields must match v1 exactly")
    if value.get("format") != REQUEST_FORMAT:
        raise MotionReferenceMaterializerError("request format mismatch")
    _v1(value.get("version"))
    if value.get("adapter") != ADAPTER or args.bodyrig_adapter != ADAPTER:
        raise MotionReferenceMaterializerError("adapter identity mismatch")
    revision = _self_revision()
    if value.get("revision") != revision or args.bodyrig_revision != revision:
        raise MotionReferenceMaterializerError("materializer revision does not match exact adapter bytes")
    for key in (
        "teacher_input_sha256", "animation_execution_receipt_sha256",
        "held_out_reference_catalog_sha256", "animated_review_plan_sha256",
    ):
        _sha(value.get(key), label=key)
    sample_fps = value.get("sample_fps")
    if isinstance(sample_fps, bool) or not isinstance(sample_fps, (int, float)) or float(sample_fps) != 24.0:
        raise MotionReferenceMaterializerError("motion materializer sample_fps must be exactly 24")
    if value.get("decode_semantics") != "opencv-bgr-array-v1":
        raise MotionReferenceMaterializerError("decode semantics mismatch")
    if value.get("frame_hash_semantics") != "sha256(shape-ascii-newline+contiguous-bgr-bytes)":
        raise MotionReferenceMaterializerError("frame hash semantics mismatch")
    if value.get("teacher_process_disclosure") is not False:
        raise MotionReferenceMaterializerError("request crossed teacher disclosure boundary")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise MotionReferenceMaterializerError("request build/runtime boundary is invalid")
    if value.get("animated_teacher_acceptance_authority") is not False:
        raise MotionReferenceMaterializerError("request crossed animated-teacher authority")
    if value.get("p3_device_distillation_authorized") is not False or value.get("production_activation") is not False:
        raise MotionReferenceMaterializerError("request crossed downstream authority")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise MotionReferenceMaterializerError("request has no held-out video sources")
    source_count = value.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count != len(sources):
        raise MotionReferenceMaterializerError("request source_count mismatch")
    windows = sum(len(source.get("windows") or []) for source in sources if isinstance(source, Mapping))
    window_count = value.get("window_count")
    if isinstance(window_count, bool) or not isinstance(window_count, int) or window_count != windows or windows < 1:
        raise MotionReferenceMaterializerError("request window_count mismatch")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact held-out motion review windows as deterministic PNG sequences")
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # noqa: BLE001
            raise MotionReferenceMaterializerError("OpenCV and NumPy are required in the pinned Photoreal runtime") from exc
        request = _read_json(args.bodyrig_request.expanduser().resolve())
        _validate_request(request, args)
        output = args.bodyrig_output.expanduser().resolve()
        if not output.is_dir() or any(output.iterdir()):
            raise MotionReferenceMaterializerError("BodyRig output directory must exist and be empty")
        motion_root = output / "motion"
        motion_root.mkdir()
        materialized: list[dict[str, Any]] = []
        seen_windows: set[str] = set()
        for source in request["sources"]:
            if not isinstance(source, Mapping):
                raise MotionReferenceMaterializerError("request contains invalid source")
            source_key = _text(source.get("source_key"), label="source key")
            path = Path(_text(source.get("resolved_path"), label="resolved source path"))
            if source.get("kind") != "video" or source.get("projection") != "flat":
                raise MotionReferenceMaterializerError("motion materializer v1 requires flat held-out video")
            layout = _text(source.get("stereo_layout"), label="stereo layout", maximum=128)
            if layout not in {"mono", "side-by-side", "over-under"}:
                raise MotionReferenceMaterializerError("motion materializer stereo layout is unsupported")
            if not path.is_file():
                raise MotionReferenceMaterializerError(f"held-out motion source not found: {path}")
            if _file_sha(path) != _sha(source.get("source_sha256"), label="source SHA-256"):
                raise MotionReferenceMaterializerError("held-out motion source SHA-256 mismatch")
            capture = cv2.VideoCapture(str(path))
            try:
                if not capture.isOpened():
                    raise MotionReferenceMaterializerError(f"could not open held-out video: {path}")
                windows = source.get("windows")
                if not isinstance(windows, list) or not windows:
                    raise MotionReferenceMaterializerError("held-out motion source contains no windows")
                for window in windows:
                    if not isinstance(window, Mapping):
                        raise MotionReferenceMaterializerError("motion window is invalid")
                    window_id = _sha(window.get("window_id"), label="motion window id")
                    if window_id in seen_windows:
                        raise MotionReferenceMaterializerError("request repeats motion window id")
                    seen_windows.add(window_id)
                    eye = _text(window.get("eye"), label="motion window eye", maximum=16)
                    start = _finite(window.get("window_start_seconds"), label="motion window start")
                    end = _finite(window.get("window_end_seconds"), label="motion window end")
                    if end <= start:
                        raise MotionReferenceMaterializerError("motion window is empty")
                    dimensions = window.get("dimensions")
                    if not isinstance(dimensions, list) or not dimensions or any(not isinstance(item, str) or not item for item in dimensions):
                        raise MotionReferenceMaterializerError("motion window dimensions are invalid")
                    anchors = window.get("anchors")
                    if not isinstance(anchors, list) or not anchors:
                        raise MotionReferenceMaterializerError("motion window has no anchor observations")
                    verified_anchors: list[dict[str, Any]] = []
                    for anchor in anchors:
                        if not isinstance(anchor, Mapping):
                            raise MotionReferenceMaterializerError("motion anchor is invalid")
                        observation_id = _sha(anchor.get("observation_id"), label="motion anchor observation id")
                        timestamp = _finite(anchor.get("timestamp_seconds"), label="motion anchor timestamp")
                        if not start <= timestamp <= end:
                            raise MotionReferenceMaterializerError("motion anchor timestamp lies outside window")
                        expected_sha = _sha(anchor.get("expected_frame_sha256"), label="expected anchor frame SHA-256")
                        image = _decode_at(cv2, np, capture, timestamp=timestamp, layout=layout, eye=eye)
                        observed_sha = _frame_sha(image)
                        if observed_sha != expected_sha:
                            raise MotionReferenceMaterializerError(
                                f"held-out motion anchor frame SHA-256 mismatch for observation {observation_id}"
                            )
                        anchor_dimensions = anchor.get("dimensions")
                        if not isinstance(anchor_dimensions, list) or not anchor_dimensions:
                            raise MotionReferenceMaterializerError("motion anchor dimensions are invalid")
                        verified_anchors.append({
                            "observation_id": observation_id,
                            "timestamp_seconds": timestamp,
                            "expected_frame_sha256": expected_sha,
                            "observed_frame_sha256": observed_sha,
                            "dimensions": list(anchor_dimensions),
                            "frame_hash_verified": True,
                        })

                    duration = end - start
                    frame_count = int(math.floor(duration * float(request["sample_fps"]))) + 1
                    if frame_count < 2 or frame_count > MAX_FRAMES_PER_WINDOW:
                        raise MotionReferenceMaterializerError(
                            f"motion window frame count {frame_count} exceeds safety bound {MAX_FRAMES_PER_WINDOW}"
                        )
                    window_dir = motion_root / window_id
                    window_dir.mkdir()
                    frames: list[dict[str, Any]] = []
                    for index in range(frame_count):
                        timestamp = round(min(end, start + index / float(request["sample_fps"])), 6)
                        image = _decode_at(cv2, np, capture, timestamp=timestamp, layout=layout, eye=eye)
                        decoded_sha = _frame_sha(image)
                        target = window_dir / f"{index:04d}.png"
                        if not cv2.imwrite(str(target), image):
                            raise MotionReferenceMaterializerError(f"could not write motion review PNG: {target}")
                        if not target.is_file() or target.stat().st_size < 1:
                            raise MotionReferenceMaterializerError(f"motion review PNG is missing after write: {target}")
                        frames.append({
                            "index": index,
                            "requested_timestamp_seconds": timestamp,
                            "decoded_frame_sha256": decoded_sha,
                            "png_relative_path": f"motion/{window_id}/{index:04d}.png",
                            "png_size_bytes": target.stat().st_size,
                            "png_sha256": _file_sha(target),
                        })
                    materialized.append({
                        "window_id": window_id,
                        "source_key": source_key,
                        "eye": eye,
                        "dimensions": sorted(set(str(item) for item in dimensions)),
                        "window_start_seconds": start,
                        "window_end_seconds": end,
                        "sample_fps": float(request["sample_fps"]),
                        "anchors": sorted(verified_anchors, key=lambda item: item["observation_id"]),
                        "source_hash_verified": True,
                        "all_anchor_hashes_verified": True,
                        "frame_count": len(frames),
                        "frames": frames,
                    })
            finally:
                capture.release()

        materialized.sort(key=lambda item: item["window_id"])
        result = {
            "format": RESULT_FORMAT,
            "version": VERSION,
            "performer_id": request["performer_id"],
            "selected_epoch_id": request["selected_epoch_id"],
            "teacher_input_sha256": request["teacher_input_sha256"],
            "animation_execution_receipt_sha256": request["animation_execution_receipt_sha256"],
            "held_out_reference_catalog_sha256": request["held_out_reference_catalog_sha256"],
            "animated_review_plan_sha256": request["animated_review_plan_sha256"],
            "adapter": ADAPTER,
            "revision": request["revision"],
            "sample_fps": request["sample_fps"],
            "source_count": request["source_count"],
            "window_count": request["window_count"],
            "materialized_windows": materialized,
            "all_source_hashes_verified": True,
            "all_anchor_hashes_verified": True,
            "decode_semantics": request["decode_semantics"],
            "frame_hash_semantics": request["frame_hash_semantics"],
            "teacher_process_disclosure": False,
            "reference_motion_bytes_materialized": True,
            "human_animated_visual_acceptance_required": True,
            "animated_teacher_acceptance_authority": False,
            "p3_device_distillation_authorized": False,
            "build_only": True,
            "runtime_dependency": False,
            "production_activation": False,
        }
        (output / "motion-materialization-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "format": RESULT_FORMAT,
            "version": VERSION,
            "window_count": len(materialized),
            "all_source_hashes_verified": True,
            "all_anchor_hashes_verified": True,
            "reference_motion_bytes_materialized": True,
            "animated_teacher_acceptance_authority": False,
            "p3_device_distillation_authorized": False,
            "production_activation": False,
        }, sort_keys=True, separators=(",", ":")))
    except MotionReferenceMaterializerError as exc:
        print(f"BodyRig motion reference materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
