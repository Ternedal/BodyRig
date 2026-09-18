from __future__ import annotations

import pytest

from bodyrig.photoreal_frame_index import PhotorealFrameIndexError, build_frame_index


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [
            {
                "source_id": "scene:train:E:/train.mp4",
                "group_id": "scene:train",
                "kind": "video",
            }
        ],
        "evaluation": [
            {
                "source_id": "scene:eval:E:/eval.mp4",
                "group_id": "scene:eval",
                "kind": "video",
            }
        ],
        "held_out_view_coverage_required": ["face-front"],
        "rear_view_required_when_source_observable": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:train:E:/train.mp4",
                "kind": "video",
                "sha256": "a" * 64,
            },
            {
                "source_key": "scene:eval:E:/eval.mp4",
                "kind": "video",
                "sha256": "b" * 64,
            },
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observation(*, similarity: float) -> dict[str, object]:
    return {
        "source_key": "scene:train:E:/train.mp4",
        "source_sha256": "a" * 64,
        "kind": "video",
        "timestamp_seconds": 1.0,
        "eye": "mono",
        "projection": "flat",
        "frame_sha256": "1" * 64,
        "perceptual_hash": "0123456789abcdef",
        "candidate_id": "person-0",
        "person_detected": True,
        "measured_person_candidate_count": 1,
        "identity_sample_ambiguous": False,
        "width": 1920,
        "height": 1080,
        "view_bin": "front",
        "face_visibility": 0.9,
        "full_body_visibility": 0.9,
        "person_fraction": 0.8,
        "sharpness": 0.9,
        "motion": 0.1,
        "occlusion": 0.1,
        "identity_measurement_status": "available",
        "identity_similarity": similarity,
        "identity_authority": "calibrated-identity-bank-v1",
        "target_identity_verified": True,
    }


def _authorized_observations(*, similarity: float) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-authorized-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "frame-test",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": "c" * 64,
        "identity_bank_sha256": "d" * 64,
        "identity_calibration_sha256": "e" * 64,
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.8,
        "identity_ambiguous_sample_count": 0,
        "observations": [_observation(similarity=similarity)],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def test_frame_index_rejects_calibrated_authority_below_threshold() -> None:
    with pytest.raises(PhotorealFrameIndexError, match="below the calibrated match threshold"):
        build_frame_index(_plan(), _receipt(), _authorized_observations(similarity=0.79))
