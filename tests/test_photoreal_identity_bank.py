from __future__ import annotations

import copy
import math

import pytest

from bodyrig.photoreal_identity_bank import PhotorealIdentityBankError, build_identity_bank


def _bootstrap() -> dict[str, object]:
    return {
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
                    {"timestamp_seconds": 3.0, "eye": "mono"},
                ],
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "group_id": "image:i1",
                "reference_samples": [{"timestamp_seconds": None, "eye": "mono"}],
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


def _model_set() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-analyzer-model-set",
        "version": 1,
        "model_set_sha256": "c" * 64,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _vec(seed: int, dimension: int = 32) -> list[float]:
    values = [0.0] * dimension
    values[0] = 1.0
    values[1] = seed / 100.0
    return values


def _observations() -> dict[str, object]:
    return {
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
                "embedding": _vec(1),
            },
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "timestamp_seconds": 2.0,
                "eye": "mono",
                "frame_sha256": "2" * 64,
                "embedding": _vec(2),
            },
            {
                "source_key": "scene:s1:E:/a.mp4",
                "source_sha256": "a" * 64,
                "timestamp_seconds": 3.0,
                "eye": "mono",
                "frame_sha256": "3" * 64,
                "embedding": _vec(3),
            },
            {
                "source_key": "image:i1:F:/portrait.jpg",
                "source_sha256": "b" * 64,
                "timestamp_seconds": None,
                "eye": "mono",
                "frame_sha256": "4" * 64,
                "embedding": _vec(4),
            },
        ],
        "build_only": True,
        "production_activation": False,
    }


def test_identity_bank_is_train_only_byte_and_model_bound() -> None:
    result = build_identity_bank(_bootstrap(), _model_set(), _observations())

    assert result["performer_id"] == "42"
    assert result["model_set_sha256"] == "c" * 64
    assert result["reference_count"] == 4
    assert result["source_group_count"] == 2
    assert result["train_only"] is True
    assert result["evaluation_reference_count"] == 0
    assert result["match_threshold_calibrated"] is False
    assert result["identity_matching_authorized"] is False
    assert result["identity_bank_ready_for_calibration"] is True
    assert result["teacher_training_authorized"] is False
    assert result["production_activation"] is False
    assert len(result["identity_bank_sha256"]) == 64


def test_identity_bank_normalizes_embeddings_in_core() -> None:
    observations = _observations()
    observations["observations"][0]["embedding"] = [10.0, 2.0] + [0.0] * 30

    result = build_identity_bank(_bootstrap(), _model_set(), observations)
    vector = result["references"][0]["embedding"]

    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-7, abs_tol=1e-7)


def test_identity_bank_rejects_different_model_set() -> None:
    observations = _observations()
    observations["model_set_sha256"] = "d" * 64

    with pytest.raises(PhotorealIdentityBankError, match="different model set"):
        build_identity_bank(_bootstrap(), _model_set(), observations)


def test_identity_bank_rejects_source_byte_change() -> None:
    observations = _observations()
    observations["observations"][0]["source_sha256"] = "f" * 64

    with pytest.raises(PhotorealIdentityBankError, match="source bytes changed"):
        build_identity_bank(_bootstrap(), _model_set(), observations)


def test_identity_bank_rejects_unplanned_reference_sample() -> None:
    observations = _observations()
    observations["observations"][0]["timestamp_seconds"] = 999.0

    with pytest.raises(PhotorealIdentityBankError, match="not authorized by bootstrap plan"):
        build_identity_bank(_bootstrap(), _model_set(), observations)


def test_identity_bank_rejects_eval_or_other_source() -> None:
    observations = _observations()
    observations["observations"][0]["source_key"] = "scene:s-eval:E:/eval.mp4"

    with pytest.raises(PhotorealIdentityBankError, match="non-authoritative source"):
        build_identity_bank(_bootstrap(), _model_set(), observations)


def test_identity_bank_requires_two_train_groups_in_actual_references() -> None:
    observations = _observations()
    observations["observations"][-1] = copy.deepcopy(observations["observations"][0])
    observations["observations"][-1]["frame_sha256"] = "5" * 64

    with pytest.raises(PhotorealIdentityBankError, match="independent train groups"):
        build_identity_bank(_bootstrap(), _model_set(), observations)


def test_identity_bank_rejects_zero_embedding() -> None:
    observations = _observations()
    observations["observations"][0]["embedding"] = [0.0] * 32

    with pytest.raises(PhotorealIdentityBankError, match="zero/invalid norm"):
        build_identity_bank(_bootstrap(), _model_set(), observations)
