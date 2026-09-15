from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_bank import build_identity_bank
from bodyrig.photoreal_identity_calibration import (
    PhotorealIdentityCalibrationError,
    build_identity_calibration,
)
from bodyrig.photoreal_identity_calibration_plan import build_identity_calibration_plan


def _vec(primary: int, secondary: float = 0.0, dimension: int = 32) -> list[float]:
    value = [0.0] * dimension
    value[primary] = 1.0
    value[(primary + 1) % dimension] = secondary
    return value


def _bank() -> dict[str, object]:
    bootstrap = {
        "format": "bodyrig-photoreal-identity-bootstrap-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "sources": [
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "group_id": "scene:s1",
                "reference_samples": [
                    {"timestamp_seconds": 1.0, "eye": "mono"},
                    {"timestamp_seconds": 2.0, "eye": "mono"},
                ],
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "group_id": "image:i1",
                "reference_samples": [
                    {"timestamp_seconds": None, "eye": "mono"},
                    {"timestamp_seconds": 3.0, "eye": "mono"},
                ],
            },
        ],
        "train_only": True,
        "evaluation_source_count": 0,
        "source_bytes_bound": True,
        "identity_bank_build_authorized": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    model_set = {
        "format": "bodyrig-photoreal-analyzer-model-set",
        "version": 1,
        "model_set_sha256": "c" * 64,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    observations = {
        "format": "bodyrig-photoreal-identity-reference-observations",
        "version": 1,
        "performer_id": "42",
        "extractor": "identity-test",
        "extractor_revision": "r1",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 32,
        "observations": [
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "frame_sha256": "1" * 64,
                "embedding": _vec(0, 0.01),
            },
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "timestamp_seconds": 2.0,
                "eye": "mono",
                "frame_sha256": "2" * 64,
                "embedding": _vec(0, 0.02),
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "timestamp_seconds": None,
                "eye": "mono",
                "frame_sha256": "3" * 64,
                "embedding": _vec(0, 0.015),
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "timestamp_seconds": 3.0,
                "eye": "mono",
                "frame_sha256": "4" * 64,
                "embedding": _vec(0, 0.025),
            },
        ],
        "build_only": True,
        "production_activation": False,
    }
    return build_identity_bank(bootstrap, model_set, observations)


def _negative_receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-negative-receipt",
        "version": 1,
        "target_performer_id": "42",
        "negative_inventory_sha256": "e" * 64,
        "label_authority": "stash-single-performer-other-id-v1",
        "sources": [
            {
                "source_key": "scene:s7:E:/p7.mp4",
                "sha256": "7" * 64,
                "resolved_path": r"\\stash\VR_E\p7.mp4",
                "subject_performer_id": "7",
                "subject_performer_name": "P7",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 60.0,
            },
            {
                "source_key": "scene:s8:E:/p8.mp4",
                "sha256": "8" * 64,
                "resolved_path": r"\\stash\VR_E\p8.mp4",
                "subject_performer_id": "8",
                "subject_performer_name": "P8",
                "target_performer_id": "42",
                "target_performer_absent": True,
                "label_authority": "stash-single-performer-other-id-v1",
                "kind": "video",
                "source_binding": "scene-single-performer",
                "projection": "flat",
                "stereo_layout": "mono",
                "duration_seconds": 60.0,
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


def _plan(bank: dict[str, object]) -> dict[str, object]:
    return build_identity_calibration_plan(bank, _negative_receipt())


def _negative_observations(bank: dict[str, object], plan: dict[str, object]) -> dict[str, object]:
    observations = []
    frame = 5
    for source_index, source in enumerate(plan["sources"]):
        for sample in source["samples"][:4]:
            observations.append(
                {
                    "source_key": source["source_key"],
                    "source_sha256": source["source_sha256"],
                    "subject_performer_id": source["subject_performer_id"],
                    "timestamp_seconds": sample["timestamp_seconds"],
                    "eye": sample["eye"],
                    "frame_sha256": format(frame, "x") * 64,
                    "embedding": _vec(5 + source_index, 0.02),
                }
            )
            frame += 1
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": "42",
        "identity_bank_sha256": bank["identity_bank_sha256"],
        "extractor": bank["extractor"],
        "extractor_revision": bank["extractor_revision"],
        "model_set_sha256": bank["model_set_sha256"],
        "embedding_dimension": bank["embedding_dimension"],
        "observations": observations,
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def test_calibration_authorizes_only_after_data_separation() -> None:
    bank = _bank()
    plan = _plan(bank)
    result = build_identity_calibration(bank, plan, _negative_observations(bank, plan))

    assert result["negative_observation_count"] == 8
    assert result["negative_performer_count"] == 2
    assert result["observed_separation_margin"] >= 0.05
    assert result["match_threshold"] is not None
    assert result["negative_to_target_centroid_cosine_max"] < result["match_threshold"]
    assert result["match_threshold"] < result["positive_leave_group_out_cosine_min"]
    assert result["match_threshold_calibrated"] is True
    assert result["identity_matching_authorized"] is True
    assert result["calibration_blockers"] == []
    assert result["calibration_data_teacher_input"] is False
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False
    assert len(result["identity_calibration_sha256"]) == 64


def test_calibration_refuses_threshold_when_negatives_overlap_target() -> None:
    bank = _bank()
    plan = _plan(bank)
    observations = _negative_observations(bank, plan)
    for item in observations["observations"]:
        item["embedding"] = _vec(0, 0.01)

    result = build_identity_calibration(bank, plan, observations)

    assert result["observed_separation_margin"] < 0.05
    assert result["match_threshold"] is None
    assert result["match_threshold_calibrated"] is False
    assert result["identity_matching_authorized"] is False
    assert any("below required" in blocker for blocker in result["calibration_blockers"])


def test_calibration_refuses_threshold_with_too_few_negative_observations() -> None:
    bank = _bank()
    plan = _plan(bank)
    observations = _negative_observations(bank, plan)
    observations["observations"] = observations["observations"][:6]

    result = build_identity_calibration(bank, plan, observations)

    assert result["negative_observation_count"] == 6
    assert result["match_threshold"] is None
    assert result["identity_matching_authorized"] is False
    assert "requires at least 8 negative observations" in result["calibration_blockers"]


def test_calibration_refuses_threshold_with_one_negative_performer() -> None:
    bank = _bank()
    plan = _plan(bank)
    observations = _negative_observations(bank, plan)
    for item in observations["observations"]:
        item["subject_performer_id"] = "7"
    for source in plan["sources"]:
        source["subject_performer_id"] = "7"

    result = build_identity_calibration(bank, plan, observations)

    assert result["negative_performer_count"] == 1
    assert result["identity_matching_authorized"] is False
    assert "requires at least 2 distinct negative performers" in result["calibration_blockers"]


def test_calibration_rejects_unplanned_negative_sample() -> None:
    bank = _bank()
    plan = _plan(bank)
    observations = _negative_observations(bank, plan)
    observations["observations"][0]["timestamp_seconds"] = 999.0

    with pytest.raises(PhotorealIdentityCalibrationError, match="sample was not planned"):
        build_identity_calibration(bank, plan, observations)


def test_calibration_rejects_tampered_identity_bank() -> None:
    bank = copy.deepcopy(_bank())
    bank["references"][0]["embedding"][0] = 0.0
    plan = _plan(_bank())

    with pytest.raises(PhotorealIdentityCalibrationError, match="canonical digest mismatch"):
        build_identity_calibration(bank, plan, _negative_observations(_bank(), plan))


def test_calibration_rejects_wrong_model_set() -> None:
    bank = _bank()
    plan = _plan(bank)
    observations = _negative_observations(bank, plan)
    observations["model_set_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityCalibrationError, match="different model set"):
        build_identity_calibration(bank, plan, observations)
