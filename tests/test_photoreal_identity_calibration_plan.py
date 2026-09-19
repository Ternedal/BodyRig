from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_calibration_plan import (
    PhotorealIdentityCalibrationPlanError,
    build_identity_calibration_plan,
)


def _bank() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 512,
        "identity_bank_sha256": "d" * 64,
        "train_only": True,
        "evaluation_reference_count": 0,
        "match_threshold_calibrated": False,
        "identity_matching_authorized": False,
        "identity_bank_ready_for_calibration": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-receipt",
        "version": 1,
        "target_performer_id": "42",
        "negative_inventory_sha256": "e" * 64,
        "label_authority": "stash-single-performer-other-id-v1",
        "sources": [
            {
                "source_key": "scene:s7:E:/p7.mp4",
                "source_sha256": "a" * 64,
                "sha256": "a" * 64,
                "resolved_path": r"\\stash\VR_E\p7.mp4",
                "subject_performer_id": "7",
                "subject_performer_name": "P7",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "projection": "flat",
                "stereo_layout": "side-by-side",
                "duration_seconds": 60.0,
            },
            {
                "source_key": "image:i8:F:/p8.jpg",
                "source_sha256": "b" * 64,
                "sha256": "b" * 64,
                "resolved_path": r"\\stash\VR_F\p8.jpg",
                "subject_performer_id": "8",
                "subject_performer_name": "P8",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "image",
                "source_binding": "direct-performer",
            },
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_calibration_plan_is_byte_model_and_bank_bound() -> None:
    result = build_identity_calibration_plan(_bank(), _receipt())

    assert result["target_performer_id"] == "42"
    assert result["identity_bank_sha256"] == "d" * 64
    assert result["negative_inventory_sha256"] == "e" * 64
    assert result["model_set_sha256"] == "c" * 64
    assert result["extractor"] == "identity-test"
    assert result["extractor_revision"] == "r1"
    assert result["embedding_dimension"] == 512
    assert result["negative_performer_count"] == 2
    assert result["source_count"] == 2
    assert result["negative_embedding_extraction_required"] is True
    assert result["identity_matching_authorized"] is False
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False


def test_calibration_plan_splits_rectilinear_stereo_negative_video() -> None:
    result = build_identity_calibration_plan(_bank(), _receipt())
    video = next(item for item in result["sources"] if item["kind"] == "video")

    assert video["decode_mode"] == "rectilinear-stereo-split"
    assert result["video_timestamps_per_source"] == 320
    assert video["sample_count"] == 640
    assert {sample["eye"] for sample in video["samples"]} == {"left", "right"}
    assert len({sample["timestamp_seconds"] for sample in video["samples"]}) == 320


def test_calibration_plan_rejects_spatial_video_before_identity_extraction() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"][0]["projection"] = "vr180"

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="deprojection"):
        build_identity_calibration_plan(_bank(), receipt)


def test_calibration_plan_uses_one_direct_sample_for_image() -> None:
    result = build_identity_calibration_plan(_bank(), _receipt())
    image = next(item for item in result["sources"] if item["kind"] == "image")

    assert image["decode_mode"] == "image-direct"
    assert image["samples"] == [{"timestamp_seconds": None, "eye": "mono"}]


def test_calibration_plan_requires_two_distinct_negative_performers() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"][1]["subject_performer_id"] = "7"

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="distinct negative performers"):
        build_identity_calibration_plan(_bank(), receipt)


def test_calibration_plan_rejects_target_as_negative() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"][0]["subject_performer_id"] = "42"

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="can contain target performer"):
        build_identity_calibration_plan(_bank(), receipt)


def test_calibration_plan_rejects_uncalibrated_authority_crossing() -> None:
    bank = copy.deepcopy(_bank())
    bank["identity_matching_authorized"] = True

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="already calibrated/authorized"):
        build_identity_calibration_plan(bank, _receipt())


def test_calibration_plan_rejects_unknown_spatial_layout() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"][0]["stereo_layout"] = "unknown"

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="not decode-authoritative"):
        build_identity_calibration_plan(_bank(), receipt)


def test_calibration_plan_rejects_model_or_bank_hash_corruption() -> None:
    bank = copy.deepcopy(_bank())
    bank["identity_bank_sha256"] = "not-a-hash"

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="identity bank SHA-256"):
        build_identity_calibration_plan(bank, _receipt())


def test_calibration_plan_rejects_missing_inventory_digest() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt.pop("negative_inventory_sha256")

    with pytest.raises(PhotorealIdentityCalibrationPlanError, match="inventory SHA-256"):
        build_identity_calibration_plan(_bank(), receipt)


def test_calibration_plan_distributes_video_budget_across_sources() -> None:
    receipt = copy.deepcopy(_receipt())
    receipt["sources"] = []
    for index, performer_id in enumerate(("7", "8", "9", "10"), start=1):
        receipt["sources"].append(
            {
                "source_key": f"scene:s{index}:E:/p{performer_id}.mp4",
                "source_sha256": f"{index}" * 64,
                "sha256": f"{index}" * 64,
                "resolved_path": rf"\\stash\VR_E\p{performer_id}.mp4",
                "subject_performer_id": performer_id,
                "subject_performer_name": f"P{performer_id}",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 120.0,
            }
        )

    result = build_identity_calibration_plan(_bank(), receipt)

    assert result["video_timestamps_per_source"] == 80
    assert result["planned_negative_observation_count"] == 320
    assert all(source["sample_count"] == 80 for source in result["sources"])
    assert all(
        len({sample["timestamp_seconds"] for sample in source["samples"]}) == 80
        for source in result["sources"]
    )
