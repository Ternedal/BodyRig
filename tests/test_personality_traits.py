from __future__ import annotations

import re

import pytest

from bodyrig.personality_traits import (
    INNER_KEYS,
    OUTER_KEYS,
    PersonalityTraitProfileError,
    build_trait_profile,
    compile_trait_profile,
    trait_catalog,
    trait_profile_sha256,
    validate_trait_profile,
)


def test_catalog_has_exactly_sixty_traits_per_ring() -> None:
    catalog = trait_catalog()

    assert catalog["trait_count"] == 120
    assert len(catalog["inner_ring"]) == 60
    assert len(catalog["outer_ring"]) == 60
    assert len(INNER_KEYS) == 60
    assert len(OUTER_KEYS) == 60
    assert len(set(INNER_KEYS)) == 60
    assert len(set(OUTER_KEYS)) == 60


def test_coordination_is_ring_scoped_not_collapsed() -> None:
    profile = build_trait_profile(
        inner_ring={"coordination": 0.2},
        outer_ring={"coordination": 0.9},
    )

    assert profile["inner_ring"]["coordination"] == pytest.approx(0.2)
    assert profile["outer_ring"]["coordination"] == pytest.approx(0.9)


def test_default_profile_is_fully_neutral_and_operator_authored() -> None:
    profile = build_trait_profile()

    assert profile["grounding"] == "operator-authored"
    assert set(profile["inner_ring"]) == set(INNER_KEYS)
    assert set(profile["outer_ring"]) == set(OUTER_KEYS)
    assert all(value == 0.5 for value in profile["inner_ring"].values())
    assert all(value == 0.5 for value in profile["outer_ring"].values())


def test_validator_requires_exact_catalog_and_scale() -> None:
    profile = build_trait_profile()
    profile["inner_ring"].pop("candor")

    with pytest.raises(
        PersonalityTraitProfileError,
        match="60-trait catalog exactly",
    ):
        validate_trait_profile(profile)

    profile = build_trait_profile()
    profile["scale"]["neutral"] = 0.4
    with pytest.raises(
        PersonalityTraitProfileError,
        match="exactly 0..1 with neutral 0.5",
    ):
        validate_trait_profile(profile)


def test_builder_rejects_unknown_or_invalid_values() -> None:
    with pytest.raises(
        PersonalityTraitProfileError,
        match="unknown inner-ring traits",
    ):
        build_trait_profile(inner_ring={"not_a_trait": 0.7})

    with pytest.raises(
        PersonalityTraitProfileError,
        match=r"outer_ring\.empathy",
    ):
        build_trait_profile(outer_ring={"empathy": 1.5})

    with pytest.raises(
        PersonalityTraitProfileError,
        match=r"inner_ring\.humor",
    ):
        build_trait_profile(inner_ring={"humor": True})


def test_digest_is_deterministic_and_changes_with_trait_value() -> None:
    first = build_trait_profile(inner_ring={"curiosity": 0.8})
    same = build_trait_profile(inner_ring={"curiosity": 0.8})
    changed = build_trait_profile(inner_ring={"curiosity": 0.85})

    first_digest = trait_profile_sha256(first)
    assert first_digest == trait_profile_sha256(same)
    assert first_digest != trait_profile_sha256(changed)
    assert re.fullmatch(r"[0-9a-f]{64}", first_digest)


def test_compiler_summarizes_salient_traits_and_binds_full_vector() -> None:
    profile = build_trait_profile(
        inner_ring={
            "curiosity": 0.9,
            "timidity": 0.1,
            "humor": 0.7,
        },
        outer_ring={
            "empathy": 0.85,
            "aggression": 0.15,
            "patience": 0.7,
        },
    )

    compiled = compile_trait_profile(profile)

    assert compiled["active_trait_count"] == 6
    assert "very high Curiosity (0.90)" in compiled["instructions"]
    assert "very low Timidity (0.10)" in compiled["instructions"]
    assert "very high Empathy (0.85)" in compiled["instructions"]
    assert "very low Aggression (0.15)" in compiled["instructions"]
    assert "not diagnoses" in compiled["instructions"]
    assert "not permissions" in compiled["instructions"]
    assert "trait_profile_sha256=" in compiled["style_notes"]
    assert "inner_ring=" in compiled["style_notes"]
    assert "outer_ring=" in compiled["style_notes"]
    assert "curiosity:0.90" in compiled["style_notes"]
    assert "empathy:0.85" in compiled["style_notes"]
    assert len(compiled["style_notes"]) < 16_000


def test_neutral_compiler_does_not_invent_trait_bias() -> None:
    compiled = compile_trait_profile(build_trait_profile())

    assert compiled["active_trait_count"] == 0
    assert "All 120 authored traits are neutral" in compiled["instructions"]
    assert compiled["salient_inner"] == []
    assert compiled["salient_outer"] == []
