from __future__ import annotations

import pytest

from bodyrig import photoidentity_multiperformer_track_runner as runner


def _review(*, version=1, source_index=0) -> dict:
    return {
        "format": "bodyrig-phalp-track-review",
        "version": version,
        "source_index": source_index,
        "tracks": [],
        "target_track_id": None,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }


def _batch(*, version=1, source_index=0, review=None) -> dict:
    return {
        "format": runner.FORMAT,
        "version": version,
        "adapter": runner.ADAPTER_NAME,
        "revision": runner.ADAPTER_REVISION,
        "sources": [
            {
                "source_index": source_index,
                "source_media_sha256": "a" * 64,
                "review": _review() if review is None else review,
            }
        ],
        "target_track_selected": False,
        "human_identity_attestation_required": True,
        "appearance_embeddings_exported": False,
        "source_paths_exported": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }


def test_batch_rejects_boolean_version() -> None:
    with pytest.raises(runner.PhotoIdentityMultiTrackRunnerError, match="unsupported PHALP track review batch format/version"):
        runner.validate_track_review_batch(_batch(version=True), expected_source_count=1)


def test_nested_review_rejects_boolean_version() -> None:
    with pytest.raises(runner.PhotoIdentityMultiTrackRunnerError, match="unsupported PHALP track review format/version"):
        runner.validate_track_review_batch(_batch(review=_review(version=True)), expected_source_count=1)


def test_batch_source_row_rejects_boolean_source_index() -> None:
    with pytest.raises(runner.PhotoIdentityMultiTrackRunnerError, match="PHALP source review ordering changed"):
        runner.validate_track_review_batch(_batch(source_index=False), expected_source_count=1)


def test_nested_review_rejects_boolean_source_index() -> None:
    with pytest.raises(runner.PhotoIdentityMultiTrackRunnerError, match="PHALP track review source index changed"):
        runner.validate_track_review_batch(_batch(review=_review(source_index=False)), expected_source_count=1)


def test_numeric_float_versions_remain_v1_compatible() -> None:
    result = runner.validate_track_review_batch(
        _batch(version=1.0, review=_review(version=1.0)),
        expected_source_count=1,
    )

    assert result["version"] == 1.0
    assert result["sources"][0]["review"]["version"] == 1.0


def test_ordinary_integer_source_indexes_remain_valid() -> None:
    result = runner.validate_track_review_batch(_batch(), expected_source_count=1)

    assert result["sources"][0]["source_index"] == 0
    assert result["sources"][0]["review"]["source_index"] == 0
