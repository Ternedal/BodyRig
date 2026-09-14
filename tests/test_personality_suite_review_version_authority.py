from __future__ import annotations

from typing import Any

import pytest

from bodyrig import personality_suite_review as review


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _review(version: Any) -> dict[str, Any]:
    probes = []
    for index in range(6):
        probes.append(
            {
                "probe_id": f"probe-{index}",
                "audition_id": f"audition-{index:032x}",
                "prompt_sha256": "a" * 64,
                "audition_receipt_sha256": "b" * 64,
                "reply_sha256": "c" * 64,
                "audio_sha256": "d" * 64,
            }
        )
    return {
        "format": review.FORMAT,
        "version": version,
        "review_id": "suite-review-" + "1" * 32,
        "person_id": "person-" + "2" * 32,
        "created_utc": "2026-09-14T17:45:00Z",
        "body_revision": "body-r0001",
        "voice_revision": "voice-r0001",
        "personality_revision": "personality-r0001",
        "assembly_fingerprint": "e" * 64,
        "modelrig_version": "modelrig-test",
        "model": "test-model",
        "voicerig_version": "voicerig-test",
        "default_language": "da",
        "suite_definition_sha256": "f" * 64,
        "probe_results": probes,
        "human_review_required": True,
        "activation_authority": False,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_suite_review_rejects_boolean_non_numeric_and_wrong_v1(version: Any) -> None:
    with pytest.raises(
        review.PersonalitySuiteReviewError,
        match="unsupported suite review format/version",
    ):
        review.validate_suite_review(_review(version))


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_suite_review_preserves_numeric_v1_and_review_only_authority(version: Any) -> None:
    value = review.validate_suite_review(_review(version))

    assert value["version"] == review.VERSION
    assert len(value["probe_results"]) == 6
    assert value["human_review_required"] is True
    assert value["activation_authority"] is False
