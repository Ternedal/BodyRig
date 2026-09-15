from __future__ import annotations

import copy
import hashlib
import json

import pytest

from bodyrig.photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from bodyrig.photoreal_motion_reference_materializer import ADAPTER, SAMPLE_FPS
from bodyrig.photoreal_motion_reference_receipt_authority import (
    PhotorealMotionReferenceReceiptAuthorityError,
    validate_motion_materialization_receipt_strict,
)


def _digest(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "motion_materialization_receipt_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _window_id(source_key: str, eye: str, start: float, end: float) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "source_key": source_key,
                "eye": eye,
                "window_start_seconds": start,
                "window_end_seconds": end,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _observation_id(source_key: str, frame_sha: str, timestamp: float, eye: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "source_key": source_key,
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": eye,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _receipt() -> dict[str, object]:
    source_key = "scene:eval:E:/held-out.mp4"
    eye = "mono"
    start = 11.5
    end = 12.5
    timestamp = 12.0
    frame_sha = "4" * 64
    window_id = _window_id(source_key, eye, start, end)
    observation_id = _observation_id(source_key, frame_sha, timestamp, eye)
    dimensions = list(MOTION_REVIEW_DIMENSIONS)
    frame_count = int((end - start) * SAMPLE_FPS) + 1
    frames = []
    for index in range(frame_count):
        requested = round(min(end, start + index / SAMPLE_FPS), 6)
        frames.append(
            {
                "index": index,
                "requested_timestamp_seconds": requested,
                "decoded_frame_sha256": format((index % 15) + 1, "x") * 64,
                "png_relative_path": f"motion/{window_id}/{index:04d}.png",
                "png_size_bytes": index + 1,
                "png_sha256": format(((index + 1) % 15) + 1, "x") * 64,
            }
        )
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-motion-reference-materialization-receipt",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "animation_execution_receipt_sha256": "b" * 64,
        "held_out_reference_catalog_sha256": "c" * 64,
        "animated_review_plan_sha256": "d" * 64,
        "adapter": ADAPTER,
        "revision": "9" * 64,
        "sample_fps": SAMPLE_FPS,
        "source_count": 1,
        "window_count": 1,
        "materialized_windows": [
            {
                "window_id": window_id,
                "source_key": source_key,
                "eye": eye,
                "dimensions": dimensions,
                "window_start_seconds": start,
                "window_end_seconds": end,
                "sample_fps": SAMPLE_FPS,
                "anchors": [
                    {
                        "observation_id": observation_id,
                        "timestamp_seconds": timestamp,
                        "expected_frame_sha256": frame_sha,
                        "observed_frame_sha256": frame_sha,
                        "dimensions": dimensions,
                        "frame_hash_verified": True,
                    }
                ],
                "source_hash_verified": True,
                "all_anchor_hashes_verified": True,
                "frame_count": frame_count,
                "frames": frames,
            }
        ],
        "all_source_hashes_verified": True,
        "all_anchor_hashes_verified": True,
        "artifact_bytes_verified_by_core": True,
        "decode_semantics": "opencv-bgr-array-v1",
        "frame_hash_semantics": "sha256(shape-ascii-newline+contiguous-bgr-bytes)",
        "teacher_process_disclosure": False,
        "reference_motion_bytes_materialized": True,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["motion_materialization_receipt_sha256"] = _digest(value)
    return value


def _reseal(value: dict[str, object]) -> None:
    value["motion_materialization_receipt_sha256"] = _digest(value)


def test_strict_receipt_accepts_canonical_self_consistent_receipt() -> None:
    result = validate_motion_materialization_receipt_strict(_receipt())
    assert result["source_count"] == 1
    assert result["window_count"] == 1
    assert result["reference_motion_bytes_materialized"] is True
    assert result["animated_teacher_acceptance_authority"] is False
    assert result["p3_device_distillation_authorized"] is False


def test_strict_receipt_rejects_resealed_window_eye_substitution() -> None:
    value = _receipt()
    value["materialized_windows"][0]["eye"] = "left"
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="window id does not match provenance"):
        validate_motion_materialization_receipt_strict(value)


def test_strict_receipt_rejects_resealed_observation_id_substitution() -> None:
    value = _receipt()
    value["materialized_windows"][0]["anchors"][0]["observation_id"] = "e" * 64
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="observation id does not match provenance"):
        validate_motion_materialization_receipt_strict(value)


def test_strict_receipt_rejects_resealed_frame_cadence_tamper() -> None:
    value = _receipt()
    value["materialized_windows"][0]["frames"][1]["requested_timestamp_seconds"] += 0.01
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="deterministic cadence"):
        validate_motion_materialization_receipt_strict(value)


def test_strict_receipt_rejects_resealed_incomplete_motion_dimension_universe() -> None:
    value = _receipt()
    missing = MOTION_REVIEW_DIMENSIONS[-1]
    value["materialized_windows"][0]["dimensions"].remove(missing)
    value["materialized_windows"][0]["anchors"][0]["dimensions"].remove(missing)
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="canonical motion-review universe"):
        validate_motion_materialization_receipt_strict(value)


def test_strict_receipt_rejects_resealed_noncanonical_png_path() -> None:
    value = _receipt()
    value["materialized_windows"][0]["frames"][0]["png_relative_path"] = "motion/elsewhere/0000.png"
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="PNG path is not canonical"):
        validate_motion_materialization_receipt_strict(value)


def test_strict_receipt_rejects_boolean_version_even_if_resealed() -> None:
    value = _receipt()
    value["version"] = True
    _reseal(value)
    with pytest.raises(PhotorealMotionReferenceReceiptAuthorityError, match="version mismatch"):
        validate_motion_materialization_receipt_strict(value)
