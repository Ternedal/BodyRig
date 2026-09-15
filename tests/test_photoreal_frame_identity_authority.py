from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identities,
)


def _plan() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "train": [
            {
                "source_id": "scene:single:E:/single.mp4",
                "group_id": "scene:single",
                "kind": "video",
                "performer_count": 1,
                "source_binding": "scene-performer",
            },
            {
                "source_id": "scene:multi:E:/multi.mp4",
                "group_id": "scene:multi",
                "kind": "video",
                "performer_count": 2,
                "source_binding": "scene-performer",
            },
        ],
        "evaluation": [
            {
                "source_id": "image:gallery:F:/gallery.jpg",
                "group_id": "gallery:g1",
                "kind": "image",
                "performer_count": 0,
                "source_binding": "performer-gallery",
            }
        ],
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _bank() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-bank",
        "version": 1,
        "performer_id": "42",
        "model_set_sha256": "c" * 64,
        "embedding_dimension": 32,
        "centroid_embedding": [1.0] + [0.0] * 31,
        "identity_bank_sha256": "d" * 64,
        "train_only": True,
        "evaluation_reference_count": 0,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _calibration(*, authorized: bool = True) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-identity-calibration",
        "version": 1,
        "identity_bank_sha256": "d" * 64,
        "model_set_sha256": "c" * 64,
        "identity_matching_authorized": authorized,
        "match_threshold_calibrated": authorized,
        "match_threshold": 0.8 if authorized else None,
        "calibration_blockers": [] if authorized else ["insufficient separation"],
        "identity_calibration_sha256": "e" * 64,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _observation(
    source_key: str,
    embedding: list[float] | None,
    *,
    candidate_id: str = "person-0",
    person_detected: bool = True,
    timestamp: float = 1.0,
) -> dict[str, object]:
    kind = "image" if source_key.startswith("image:") else "video"
    return {
        "source_key": source_key,
        "source_sha256": "a" * 64,
        "kind": kind,
        "timestamp_seconds": None if kind == "image" else timestamp,
        "eye": "mono",
        "projection": "flat",
        "frame_sha256": ("1" if "single" in source_key else "2" if "multi" in source_key else "3") * 64,
        "perceptual_hash": "0123456789abcdef",
        "candidate_id": candidate_id,
        "person_detected": person_detected,
        "width": 1920,
        "height": 1080,
        "view_bin": "front" if person_detected else "unknown",
        "face_visibility": 0.9 if person_detected else 0.0,
        "full_body_visibility": 0.9 if person_detected else 0.0,
        "person_fraction": 0.8 if person_detected else 0.0,
        "sharpness": 0.9,
        "motion": 0.1,
        "occlusion": 0.1,
        "identity_measurement_status": "unavailable" if embedding is None else "available",
        "identity_embedding": embedding,
    }


def _measurements() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": "42",
        "analyzer": "frame-test",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": "c" * 64,
        "identity_embedding_dimension": 32,
        "observations": [
            _observation("scene:single:E:/single.mp4", None),
            _observation("scene:multi:E:/multi.mp4", [1.0] + [0.0] * 31),
            _observation("image:gallery:F:/gallery.jpg", [0.0, 1.0] + [0.0] * 30),
        ],
        "build_only": True,
        "production_activation": False,
    }


def test_single_performer_source_is_authoritative_without_face_embedding() -> None:
    result = authorize_frame_identities(_plan(), _measurements(), _bank(), _calibration())
    item = next(row for row in result["observations"] if "single" in row["source_key"])

    assert item["target_identity_verified"] is True
    assert item["identity_authority"] == "stash-single-performer-target-binding-v1"
    assert item["identity_similarity"] is None
    assert item["measured_person_candidate_count"] == 1
    assert item["identity_sample_ambiguous"] is False
    assert result["multi_candidate_identity_safe"] is True


def test_multi_performer_source_requires_unique_calibrated_embedding_match() -> None:
    measurements = _measurements()
    measurements["observations"].insert(
        2,
        _observation(
            "scene:multi:E:/multi.mp4",
            [0.0, 1.0] + [0.0] * 30,
            candidate_id="person-1",
        ),
    )
    result = authorize_frame_identities(_plan(), measurements, _bank(), _calibration())
    candidates = [row for row in result["observations"] if "multi" in row["source_key"]]
    target = next(row for row in candidates if row["candidate_id"] == "person-0")
    other = next(row for row in candidates if row["candidate_id"] == "person-1")

    assert target["target_identity_verified"] is True
    assert target["identity_authority"] == "calibrated-identity-bank-v1"
    assert target["identity_similarity"] == 1.0
    assert target["measured_person_candidate_count"] == 2
    assert other["target_identity_verified"] is False
    assert other["identity_authority"] == "identity-unresolved-v1"
    assert result["identity_ambiguous_sample_count"] == 0


def test_two_threshold_matches_make_entire_sample_identity_ambiguous() -> None:
    measurements = _measurements()
    measurements["observations"].insert(
        2,
        _observation(
            "scene:multi:E:/multi.mp4",
            [0.99, 0.01] + [0.0] * 30,
            candidate_id="person-1",
        ),
    )
    result = authorize_frame_identities(_plan(), measurements, _bank(), _calibration())
    candidates = [row for row in result["observations"] if "multi" in row["source_key"]]

    assert len(candidates) == 2
    assert all(row["target_identity_verified"] is False for row in candidates)
    assert all(row["identity_authority"] == "identity-unresolved-v1" for row in candidates)
    assert all(row["identity_sample_ambiguous"] is True for row in candidates)
    assert result["identity_ambiguous_sample_count"] == 1


def test_single_performer_catalog_binding_does_not_override_two_detected_people() -> None:
    measurements = _measurements()
    measurements["observations"][0] = _observation(
        "scene:single:E:/single.mp4", [1.0] + [0.0] * 31, candidate_id="person-0"
    )
    measurements["observations"].insert(
        1,
        _observation(
            "scene:single:E:/single.mp4",
            [0.0, 1.0] + [0.0] * 30,
            candidate_id="person-1",
        ),
    )
    result = authorize_frame_identities(_plan(), measurements, _bank(), _calibration())
    candidates = [row for row in result["observations"] if "single" in row["source_key"]]
    target = next(row for row in candidates if row["candidate_id"] == "person-0")

    assert target["target_identity_verified"] is True
    assert target["identity_authority"] == "calibrated-identity-bank-v1"
    assert target["measured_person_candidate_count"] == 2


def test_nonmatching_gallery_observation_stays_unresolved() -> None:
    result = authorize_frame_identities(_plan(), _measurements(), _bank(), _calibration())
    item = next(row for row in result["observations"] if row["source_key"].startswith("image:"))

    assert item["target_identity_verified"] is False
    assert item["identity_authority"] == "identity-unresolved-v1"
    assert item["identity_similarity"] == 0.0


def test_uncalibrated_policy_never_matches_ambiguous_source() -> None:
    result = authorize_frame_identities(_plan(), _measurements(), _bank(), _calibration(authorized=False))
    multi = next(row for row in result["observations"] if "multi" in row["source_key"])
    single = next(row for row in result["observations"] if "single" in row["source_key"])

    assert multi["target_identity_verified"] is False
    assert multi["identity_authority"] == "identity-unresolved-v1"
    assert single["target_identity_verified"] is True
    assert result["identity_matching_calibrated"] is False
    assert result["identity_match_threshold"] is None


def test_no_person_placeholder_stays_unresolved() -> None:
    measurements = _measurements()
    measurements["observations"][0] = _observation(
        "scene:single:E:/single.mp4",
        None,
        candidate_id="none-0",
        person_detected=False,
    )
    result = authorize_frame_identities(_plan(), measurements, _bank(), _calibration())
    item = next(row for row in result["observations"] if "single" in row["source_key"])

    assert item["target_identity_verified"] is False
    assert item["measured_person_candidate_count"] == 0


def test_duplicate_candidate_id_within_sample_is_rejected() -> None:
    measurements = _measurements()
    measurements["observations"].insert(
        2,
        _observation(
            "scene:multi:E:/multi.mp4",
            [0.0, 1.0] + [0.0] * 30,
            candidate_id="person-0",
        ),
    )
    with pytest.raises(PhotorealFrameIdentityAuthorityError, match="repeated candidate id"):
        authorize_frame_identities(_plan(), measurements, _bank(), _calibration())


def test_external_identity_assertion_is_rejected() -> None:
    measurements = copy.deepcopy(_measurements())
    measurements["observations"][0]["target_identity_verified"] = True

    with pytest.raises(PhotorealFrameIdentityAuthorityError, match="attempted to assert identity authority"):
        authorize_frame_identities(_plan(), measurements, _bank(), _calibration())


def test_frame_identity_requires_same_model_set_as_bank() -> None:
    measurements = copy.deepcopy(_measurements())
    measurements["analyzer_model_set_sha256"] = "f" * 64

    with pytest.raises(PhotorealFrameIdentityAuthorityError, match="different model set"):
        authorize_frame_identities(_plan(), measurements, _bank(), _calibration())


def test_available_embedding_must_match_bank_dimension() -> None:
    measurements = copy.deepcopy(_measurements())
    measurements["observations"][1]["identity_embedding"] = [1.0, 0.0]

    with pytest.raises(PhotorealFrameIdentityAuthorityError, match="dimension mismatch"):
        authorize_frame_identities(_plan(), measurements, _bank(), _calibration())
