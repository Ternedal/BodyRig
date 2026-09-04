from __future__ import annotations

import pytest

from bodyrig.personality_audition_suite import (
    PersonalityAuditionSuiteError,
    build_audition_suite,
)


def test_danish_suite_covers_style_and_grounding_boundaries() -> None:
    suite = build_audition_suite("da")

    assert suite["human_review_required"] is True
    assert suite["activation_authority"] is False
    probes = {probe["id"]: probe for probe in suite["probes"]}
    assert set(probes) == {
        "natural-introduction",
        "gentle-disagreement",
        "small-mishap",
        "take-initiative",
        "unknown-memory-boundary",
        "uncertain-fact-boundary",
    }
    assert "playfulness" in probes["small-mishap"]["dimensions"]
    assert "initiative" in probes["take-initiative"]["dimensions"]
    assert "grounding" in probes["unknown-memory-boundary"]["dimensions"]
    assert "ferie" in probes["unknown-memory-boundary"]["prompt"].lower()


def test_non_danish_suite_uses_english_operator_prompts() -> None:
    suite = build_audition_suite("en-US")

    assert suite["default_language"] == "en-US"
    assert suite["probes"][0]["prompt"].startswith("Introduce yourself")


def test_invalid_language_is_rejected() -> None:
    with pytest.raises(PersonalityAuditionSuiteError, match="default_language"):
        build_audition_suite("not a language")
