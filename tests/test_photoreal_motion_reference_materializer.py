from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from bodyrig.photoreal_motion_reference_materialization_authority import (
    PhotorealMotionReferenceAuthorityError,
    build_motion_materialization_receipt,
    validate_motion_materialization_authority,
    validate_motion_materialization_receipt,
)
from bodyrig.photoreal_motion_reference_materializer import (
    ADAPTER,
    PhotorealMotionReferenceMaterializerError,
    build_motion_materialization_request,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _plan() -> dict[str, object]:
    selections = []
    for dimension in MOTION_REVIEW_DIMENSIONS:
        selections.append(
            {
                "dimension": dimension,
                "animation_artifact_kind": "animated-review-media",
                "animation_artifact_relative_path": "animation/motion.bin",
                "animation_artifact_size_bytes": 100,
                "animation_artifact_sha256": "1" * 64,
                "reference_observation_id": "2" * 64,
                "reference_source_key": "scene:eval:E:/held-out.mp4",
                "reference_source_group_id": "eval-group",
                "reference_source_resolved_path": r"\\stash\VR_E\held-out.mp4",
                "reference_source_sha256": "3" * 64,
                "reference_source_projection": "flat",
                "reference_source_stereo_layout": "mono",
                "reference_timestamp_seconds": 12.0,
                "reference_eye": "mono",
                "reference_view_bin": "front",
                "reference_frame_sha256": "4" * 64,
                "window_before_seconds": 0.5,
                "window_after_seconds": 0.5,
                "window_start_seconds": 11.5,
                "window_end_seconds": 12.5,
                "reference_motion_bytes_materialized": False,
            }
        )
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-animated-review-plan",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "animation_execution_receipt_sha256": "e" * 64,
        "held_out_reference_catalog_sha256": "f" * 64,
        "reviewer": "operator",
        "operator_supplied": True,
        "motion_review_dimensions": list(MOTION_REVIEW_DIMENSIONS),
        "selection_count": len(MOTION_REVIEW_DIMENSIONS),
        "selections": selections,
        "animation_artifact_bytes_reverified": True,
        "held_out_evaluation_only": True,
        "held_out_motion_reference_selection_complete": True,
        "motion_reference_materialization_required": True,
        "reference_motion_bytes_materialized": False,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "source_paths_build_private": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["animated_review_plan_sha256"] = _digest(value, "animated_review_plan_sha256")
    return value


def _request() -> dict[str, object]:
    return build_motion_materialization_request(_plan(), adapter=ADAPTER, revision="9" * 64)


def _raw_result(tmp_path: Path, request: dict[str, object]) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "output"
    window = request["sources"][0]["windows"][0]
    window_id = window["window_id"]
    root = output / "motion" / window_id
    root.mkdir(parents=True)
    start = float(window["window_start_seconds"])
    end = float(window["window_end_seconds"])
    frame_count = int((end - start) * 24.0) + 1
    frames = []
    for index in range(frame_count):
        target = root / f"{index:04d}.png"
        target.write_bytes(f"frame-{index}".encode("ascii"))
        frames.append(
            {
                "index": index,
                "requested_timestamp_seconds": round(min(end, start + index / 24.0), 6),
                "decoded_frame_sha256": format((index % 15) + 1, "x") * 64,
                "png_relative_path": f"motion/{window_id}/{index:04d}.png",
                "png_size_bytes": target.stat().st_size,
                "png_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    anchors = [
        {
            "observation_id": anchor["observation_id"],
            "timestamp_seconds": anchor["timestamp_seconds"],
            "expected_frame_sha256": anchor["expected_frame_sha256"],
            "observed_frame_sha256": anchor["expected_frame_sha256"],
            "dimensions": anchor["dimensions"],
            "frame_hash_verified": True,
        }
        for anchor in window["anchors"]
    ]
    value = {
        "format": "bodyrig-photoreal-motion-reference-materialization-result",
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "animation_execution_receipt_sha256": request["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": request["held_out_reference_catalog_sha256"],
        "animated_review_plan_sha256": request["animated_review_plan_sha256"],
        "adapter": request["adapter"],
        "revision": request["revision"],
        "sample_fps": request["sample_fps"],
        "source_count": request["source_count"],
        "window_count": request["window_count"],
        "materialized_windows": [
            {
                "window_id": window_id,
                "source_key": request["sources"][0]["source_key"],
                "eye": window["eye"],
                "dimensions": window["dimensions"],
                "window_start_seconds": start,
                "window_end_seconds": end,
                "sample_fps": 24.0,
                "anchors": anchors,
                "source_hash_verified": True,
                "all_anchor_hashes_verified": True,
                "frame_count": len(frames),
                "frames": frames,
            }
        ],
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
    return output, value


def test_request_deduplicates_same_window_and_anchor_across_motion_dimensions() -> None:
    request = _request()
    assert request["source_count"] == 1
    assert request["window_count"] == 1
    window = request["sources"][0]["windows"][0]
    assert sorted(window["dimensions"]) == sorted(MOTION_REVIEW_DIMENSIONS)
    assert len(window["anchors"]) == 1
    assert sorted(window["anchors"][0]["dimensions"]) == sorted(MOTION_REVIEW_DIMENSIONS)
    assert request["sample_fps"] == 24.0
    assert request["animated_teacher_acceptance_authority"] is False
    assert request["p3_device_distillation_authorized"] is False


def test_request_rejects_spatial_projection_even_if_plan_is_resealed() -> None:
    plan = _plan()
    for selection in plan["selections"]:
        selection["reference_source_projection"] = "vr180"
    plan["animated_review_plan_sha256"] = _digest(plan, "animated_review_plan_sha256")
    with pytest.raises(PhotorealMotionReferenceMaterializerError, match="only supports flat"):
        build_motion_materialization_request(plan, adapter=ADAPTER, revision="9" * 64)


def test_strict_materialization_authority_accepts_exact_deterministic_sequence(tmp_path: Path) -> None:
    request = _request()
    output, raw = _raw_result(tmp_path, request)
    validated = validate_motion_materialization_authority(raw, request=request, output_dir=output)
    receipt = build_motion_materialization_receipt(validated)
    receipt = validate_motion_materialization_receipt(receipt)
    assert receipt["window_count"] == 1
    assert receipt["all_source_hashes_verified"] is True
    assert receipt["all_anchor_hashes_verified"] is True
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["reference_motion_bytes_materialized"] is True
    assert receipt["animated_teacher_acceptance_authority"] is False
    assert receipt["p3_device_distillation_authorized"] is False
    assert receipt["production_activation"] is False


def test_strict_materialization_authority_rejects_anchor_substitution(tmp_path: Path) -> None:
    request = _request()
    output, raw = _raw_result(tmp_path, request)
    raw["materialized_windows"][0]["anchors"][0]["observed_frame_sha256"] = "8" * 64
    with pytest.raises(PhotorealMotionReferenceAuthorityError, match="not exactly verified"):
        validate_motion_materialization_authority(raw, request=request, output_dir=output)


def test_strict_materialization_authority_rejects_timestamp_cadence_manipulation(tmp_path: Path) -> None:
    request = _request()
    output, raw = _raw_result(tmp_path, request)
    raw["materialized_windows"][0]["frames"][1]["requested_timestamp_seconds"] += 0.01
    with pytest.raises(PhotorealMotionReferenceAuthorityError, match="deterministic cadence"):
        validate_motion_materialization_authority(raw, request=request, output_dir=output)


def test_materialization_rejects_png_byte_drift(tmp_path: Path) -> None:
    request = _request()
    output, raw = _raw_result(tmp_path, request)
    first = raw["materialized_windows"][0]["frames"][0]
    (output / first["png_relative_path"]).write_bytes(b"changed-after-materialization")
    with pytest.raises(PhotorealMotionReferenceAuthorityError, match="size mismatch|SHA-256 mismatch"):
        validate_motion_materialization_authority(raw, request=request, output_dir=output)


def test_motion_materialization_receipt_rejects_post_validation_tamper(tmp_path: Path) -> None:
    request = _request()
    output, raw = _raw_result(tmp_path, request)
    validated = validate_motion_materialization_authority(raw, request=request, output_dir=output)
    receipt = build_motion_materialization_receipt(validated)
    receipt["materialized_windows"][0]["eye"] = "left"
    with pytest.raises(PhotorealMotionReferenceAuthorityError, match="does not match content"):
        validate_motion_materialization_receipt(receipt)


def test_request_rejects_boolean_v1_even_when_plan_digest_is_resealed() -> None:
    plan = _plan()
    plan["version"] = True
    plan["animated_review_plan_sha256"] = _digest(plan, "animated_review_plan_sha256")
    with pytest.raises(PhotorealMotionReferenceMaterializerError, match="numeric v1"):
        build_motion_materialization_request(plan, adapter=ADAPTER, revision="9" * 64)
