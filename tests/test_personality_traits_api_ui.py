from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bodyrig.guided_app import (
    GuidedPersonalityRequest,
    _authoring_kwargs,
    personality_trait_catalog,
)
from bodyrig.personality_traits import INNER_KEYS, OUTER_KEYS


def _communication() -> dict[str, float]:
    return {
        "directness": 0.5,
        "warmth": 0.5,
        "playfulness": 0.5,
        "formality": 0.5,
        "verbosity": 0.5,
        "initiative": 0.5,
    }


def test_guided_trait_catalog_exposes_exact_120_axes() -> None:
    catalog = personality_trait_catalog()

    assert catalog["trait_count"] == 120
    assert len(catalog["inner_ring"]) == 60
    assert len(catalog["outer_ring"]) == 60
    assert {item["id"] for item in catalog["inner_ring"]} == set(INNER_KEYS)
    assert {item["id"] for item in catalog["outer_ring"]} == set(OUTER_KEYS)
    assert catalog["grounding"] == "operator-authored"
    assert catalog["scale"]["neutral"] == 0.5


def test_guided_request_canonicalizes_partial_trait_input() -> None:
    request = GuidedPersonalityRequest(
        communication=_communication(),
        trait_profile={
            "inner_ring": {"curiosity": 0.9},
            "outer_ring": {"empathy": 0.85},
        },
    )

    kwargs = _authoring_kwargs(request)
    profile = kwargs["trait_profile"]

    assert set(profile["inner_ring"]) == set(INNER_KEYS)
    assert set(profile["outer_ring"]) == set(OUTER_KEYS)
    assert profile["inner_ring"]["curiosity"] == pytest.approx(0.9)
    assert profile["outer_ring"]["empathy"] == pytest.approx(0.85)
    assert profile["inner_ring"]["candor"] == pytest.approx(0.5)
    assert profile["outer_ring"]["joy"] == pytest.approx(0.5)
    assert profile["grounding"] == "operator-authored"


def test_guided_request_rejects_out_of_range_trait_value() -> None:
    with pytest.raises(ValidationError):
        GuidedPersonalityRequest(
            communication=_communication(),
            trait_profile={
                "inner_ring": {"curiosity": 1.1},
                "outer_ring": {},
            },
        )


def test_guided_personality_ui_is_catalog_driven_and_trait_complete() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(
        encoding="utf-8"
    )
    person = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")

    for token in (
        "120-trait personality matrix",
        "60 Inner Ring + 60 Outer Ring",
        "traitSearch",
        "traitOnlyChanged",
        "traitReset",
        "innerTraits",
        "outerTraits",
        "/api/v1/personality/traits/catalog",
        "trait_profile: traitProfile()",
        "0.50 = neutral",
        "operator-authored",
    ):
        assert token in html

    assert "catalog.trait_count!==120" in html
    assert 'result.trait_profile_sha256' in html
    assert 'traits?.active_trait_count' in html
    assert "Guided Personality · 120 traits" in person
