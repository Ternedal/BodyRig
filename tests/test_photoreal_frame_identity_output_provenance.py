from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_frame_identity_output_provenance import (
    DIGEST_FIELD,
    PhotorealFrameIdentityOutputProvenanceError,
    canonical_frame_identity_authority_sha256,
    seal_frame_identity_authority,
    validate_frame_identity_authority_integrity,
)


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
                "candidate_id": "person-0",
                "identity_similarity": 0.9,
                "target_identity_verified": True,
            }
        ],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def test_frame_identity_authority_digest_is_canonical_across_key_order() -> None:
    left = _artifact()
    right = dict(reversed(list(left.items())))
    assert canonical_frame_identity_authority_sha256(left) == canonical_frame_identity_authority_sha256(right)


def test_frame_identity_authority_seal_preserves_input_and_validates() -> None:
    artifact = _artifact()
    sealed = seal_frame_identity_authority(artifact)

    assert DIGEST_FIELD not in artifact
    assert sealed[DIGEST_FIELD] == canonical_frame_identity_authority_sha256(artifact)
    assert validate_frame_identity_authority_integrity(sealed) == sealed[DIGEST_FIELD]


def test_frame_identity_authority_integrity_rejects_post_seal_mutation() -> None:
    sealed = seal_frame_identity_authority(_artifact())
    tampered = copy.deepcopy(sealed)
    tampered["observations"][0]["target_identity_verified"] = False

    with pytest.raises(PhotorealFrameIdentityOutputProvenanceError, match="digest mismatch"):
        validate_frame_identity_authority_integrity(tampered)


def test_frame_identity_authority_integrity_rejects_missing_digest() -> None:
    with pytest.raises(PhotorealFrameIdentityOutputProvenanceError, match="missing or invalid"):
        validate_frame_identity_authority_integrity(_artifact())


def test_frame_identity_authority_rejects_reseal() -> None:
    sealed = seal_frame_identity_authority(_artifact())
    with pytest.raises(PhotorealFrameIdentityOutputProvenanceError, match="already sealed"):
        seal_frame_identity_authority(sealed)
