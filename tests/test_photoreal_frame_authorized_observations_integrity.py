from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_frame_authorized_observations_integrity import (
    PhotorealAuthorizedObservationsIntegrityError,
    seal_authorized_observations,
    validate_authorized_observations_integrity,
)
from bodyrig.photoreal_frame_index import PhotorealFrameIndexError
from bodyrig.photoreal_frame_index_readback_authority import build_frame_index_files_strict


def _artifact() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-authorized-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "frame-test",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": "a" * 64,
        "identity_bank_sha256": "b" * 64,
        "identity_calibration_sha256": "c" * 64,
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.8,
        "identity_ambiguous_sample_count": 0,
        "observations": [
            {
                "source_key": "scene:train:E:/train.mp4",
                "identity_similarity": 0.9,
                "target_identity_verified": True,
                "identity_authority": "calibrated-identity-bank-v1",
            }
        ],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def test_seal_is_deterministic_and_validates() -> None:
    left = seal_authorized_observations(_artifact())
    right = seal_authorized_observations(_artifact())

    assert left["authorized_observations_sha256"] == right["authorized_observations_sha256"]
    assert validate_authorized_observations_integrity(left) == left["authorized_observations_sha256"]


def test_nested_observation_mutation_after_seal_fails_closed() -> None:
    sealed = seal_authorized_observations(_artifact())
    observations = sealed["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    observation["target_identity_verified"] = False

    with pytest.raises(PhotorealAuthorizedObservationsIntegrityError, match="canonical digest mismatch"):
        validate_authorized_observations_integrity(sealed)


def test_top_level_threshold_mutation_after_seal_fails_closed() -> None:
    sealed = seal_authorized_observations(_artifact())
    sealed["identity_match_threshold"] = 0.7

    with pytest.raises(PhotorealAuthorizedObservationsIntegrityError, match="canonical digest mismatch"):
        validate_authorized_observations_integrity(sealed)


def test_boolean_version_is_rejected_before_sealing() -> None:
    artifact = _artifact()
    artifact["version"] = True

    with pytest.raises(PhotorealAuthorizedObservationsIntegrityError, match="format/version mismatch"):
        seal_authorized_observations(artifact)


def test_boolean_ambiguous_count_is_rejected_before_sealing() -> None:
    artifact = _artifact()
    artifact["identity_ambiguous_sample_count"] = False

    with pytest.raises(PhotorealAuthorizedObservationsIntegrityError, match="ambiguous-sample count"):
        seal_authorized_observations(artifact)


def test_unexpected_top_level_field_is_rejected_even_if_sealing_is_attempted() -> None:
    artifact = _artifact()
    artifact["teacher_training_authorized"] = True

    with pytest.raises(PhotorealAuthorizedObservationsIntegrityError, match="key set mismatch"):
        seal_authorized_observations(artifact)


def test_frame_index_strict_readback_rejects_unsealed_artifact_before_indexing(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    receipt_path = tmp_path / "receipt.json"
    observations_path = tmp_path / "authorized-observations.json"
    output_path = tmp_path / "frame-index.json"

    plan_path.write_text("{}\n", encoding="utf-8")
    receipt_path.write_text("{}\n", encoding="utf-8")
    observations_path.write_text(json.dumps(_artifact()) + "\n", encoding="utf-8")

    with pytest.raises(PhotorealFrameIndexError, match="key set mismatch"):
        build_frame_index_files_strict(plan_path, receipt_path, observations_path, output_path)

    assert not output_path.exists()
