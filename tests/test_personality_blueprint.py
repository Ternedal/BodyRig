from __future__ import annotations

import re

import pytest

from bodyrig.personality_blueprint import (
    PersonalityBlueprintError,
    blueprint_sha256,
    build_blueprint,
    compile_blueprint,
    personality_trait_definitions,
    validate_blueprint,
)


def communication(**overrides: float) -> dict[str, float]:
    value = {
        "directness": 0.5,
        "warmth": 0.5,
        "playfulness": 0.5,
        "formality": 0.5,
        "verbosity": 0.5,
        "initiative": 0.5,
    }
    value.update(overrides)
    return value


def bodyprint() -> dict:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {
            "energy": 0.72,
            "gesture_frequency": 0.61,
            "gesture_amplitude": 0.83,
            "head_motion": 0.44,
        },
        "expression": {
            "gaze_strength": 0.68,
            "speech_motion": 0.76,
        },
    }


def test_blueprint_separates_authored_communication_from_observed_embodiment() -> None:
    value = build_blueprint(
        default_language="en",
        communication=communication(directness=0.9, warmth=0.8),
        authored_notes="Avoid generic assistant phrasing.",
        bodyprint=bodyprint(),
        body_revision="body-r0003",
    )

    assert value["grounding"] == {
        "communication": "operator-authored",
        "embodiment": "bodyprint-observed",
        "body_revision": "body-r0003",
    }
    assert value["embodiment"]["movement_energy"] == pytest.approx(0.72)
    assert value["embodiment"]["gesture_amplitude"] == pytest.approx(0.83)
    assert value["embodiment"]["gaze_strength"] == pytest.approx(0.68)


def test_compiler_is_deterministic_modelrig_ready_and_digest_bound() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(
            directness=0.9,
            warmth=0.8,
            playfulness=0.75,
            formality=0.2,
            verbosity=0.2,
            initiative=0.8,
        ),
        authored_notes="Vær tør og menneskelig, ikke serviceagtig.",
        style_exemplars=["Det går nok. Det er bare aftensmad, ikke en katastrofe."],
        bodyprint=bodyprint(),
        body_revision="body-r0001",
    )

    first = compile_blueprint(value)
    second = compile_blueprint(value)
    digest = blueprint_sha256(value)
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert first["default_language"] == "da"
    assert "notably direct" in first["instructions"]
    assert "warm" in first["instructions"]
    assert "short, compact answers" in first["instructions"]
    assert "private thoughts" in first["instructions"]
    assert "style exemplars only" in first["instructions"]
    assert "not a catastrophe" not in first["instructions"]
    assert "Det går nok" in first["instructions"]
    assert "do not treat their factual content" in first["instructions"]
    assert f"blueprint_sha256={digest}" in first["style_notes"]
    assert "style_exemplars=1" in first["style_notes"]
    assert "movement energy=0.72" in first["style_notes"]
    assert "body revision=body-r0001" in first["style_notes"]


def test_blueprint_digest_changes_when_authored_behavior_changes() -> None:
    first = build_blueprint(
        default_language="da",
        communication=communication(directness=0.2),
    )
    second = build_blueprint(
        default_language="da",
        communication=communication(directness=0.8),
    )

    assert blueprint_sha256(first) != blueprint_sha256(second)
    assert compile_blueprint(first)["style_notes"] != compile_blueprint(second)["style_notes"]


def test_style_exemplars_are_operator_selected_and_bounded() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(),
        style_exemplars=["Kort svar.", "Lidt tørt, men venligt."],
    )
    assert value["style_exemplars"] == ["Kort svar.", "Lidt tørt, men venligt."]

    with pytest.raises(PersonalityBlueprintError, match="at most 12"):
        build_blueprint(
            default_language="da",
            communication=communication(),
            style_exemplars=[f"example {index}" for index in range(13)],
        )


def test_validator_refuses_video_motion_as_inner_personality_authority() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(),
        bodyprint=bodyprint(),
        body_revision="body-r0001",
    )
    value["grounding"]["communication"] = "video-inferred"

    with pytest.raises(PersonalityBlueprintError, match="operator-authored"):
        validate_blueprint(value)


def test_missing_bodyprint_motion_fields_fall_back_without_inventing_inner_traits() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(),
        bodyprint={
            "format": "modelrig-bodyprint",
            "version": 1,
            "shape": {"height_scale": 1.0},
        },
        body_revision="body-r0002",
    )

    assert value["embodiment"] == {
        "gesture_amplitude": 0.5,
        "gesture_frequency": 0.5,
        "gaze_strength": 0.5,
        "head_motion": 0.5,
        "movement_energy": 0.5,
        "speech_motion": 0.5,
    }


def test_invalid_communication_type_is_reported_as_blueprint_error() -> None:
    with pytest.raises(PersonalityBlueprintError, match="communication.warmth"):
        build_blueprint(
            default_language="da",
            communication={**communication(), "warmth": "high"},
        )

def test_blueprint_rejects_huge_integer_ratio_with_domain_error() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(),
    )
    value["communication"]["warmth"] = 10**400

    with pytest.raises(
        PersonalityBlueprintError,
        match=r"communication\.warmth must be a finite number in 0\.\.1",
    ):
        validate_blueprint(value)


def test_blueprint_ratio_boundaries_remain_inclusive() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(directness=0.0, warmth=1.0),
    )

    assert value["communication"]["directness"] == 0.0
    assert value["communication"]["warmth"] == 1.0


def test_blueprint_rejects_boolean_version_constant() -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value["version"] = True
    with pytest.raises(PersonalityBlueprintError, match="format/version"):
        validate_blueprint(value)


def test_blueprint_preserves_schema_numeric_version_equality() -> None:
    value = build_blueprint(default_language="da", communication=communication())
    value["version"] = 1.0
    assert validate_blueprint(value)["version"] == 1



def trait_rings() -> tuple[dict[str, float], dict[str, float]]:
    definition = personality_trait_definitions()
    return (
        {item["id"]: 0.5 for item in definition["rings"]["inner"]},
        {item["id"]: 0.5 for item in definition["rings"]["outer"]},
    )


def test_v1_default_blueprint_digest_remains_stable() -> None:
    value = build_blueprint(
        default_language="da",
        communication=communication(),
    )

    assert value["version"] == 1
    assert "inner_ring" not in value
    assert "outer_ring" not in value
    assert (
        blueprint_sha256(value)
        == "238a50dd29550f85bdf44e6ef592fb709a8346817fa450fe152ad1a112570a4f"
    )


def test_v2_trait_matrix_has_exact_60_plus_60_definition() -> None:
    definition = personality_trait_definitions()

    assert definition["version"] == 2
    assert len(definition["rings"]["inner"]) == 60
    assert len(definition["rings"]["outer"]) == 60
    assert definition["rings"]["inner"][0] == {
        "id": "bulk_apperception",
        "label": "Bulk Apperception",
        "order": 1,
    }
    assert definition["rings"]["inner"][-1]["label"] == "Humility"
    assert definition["rings"]["outer"][0]["label"] == "Vivacity"
    assert definition["rings"]["outer"][-1]["label"] == "Meekness"


def test_v2_keeps_inner_and_outer_coordination_independent() -> None:
    inner, outer = trait_rings()
    inner["coordination"] = 0.1
    outer["coordination"] = 0.9

    value = build_blueprint(
        default_language="da",
        communication=communication(),
        inner_ring=inner,
        outer_ring=outer,
    )
    compiled = compile_blueprint(value)

    assert value["version"] == 2
    assert value["inner_ring"]["coordination"] == pytest.approx(0.1)
    assert value["outer_ring"]["coordination"] == pytest.approx(0.9)
    lines = compiled["instructions"].splitlines()
    inner_line = next(line for line in lines if line.startswith("Inner ring:"))
    outer_line = next(line for line in lines if line.startswith("Outer ring:"))
    assert "Coordination=0.1" in inner_line
    assert "Coordination=0.9" in outer_line
    assert "trait matrix=v2" in compiled["style_notes"]
    assert "inner ring traits=60" in compiled["style_notes"]
    assert "outer ring traits=60" in compiled["style_notes"]


def test_v2_digest_and_runtime_instructions_change_with_trait_value() -> None:
    inner, outer = trait_rings()
    first = build_blueprint(
        default_language="da",
        communication=communication(),
        inner_ring=inner,
        outer_ring=outer,
    )
    outer_changed = dict(outer)
    outer_changed["aggression"] = 0.95
    second = build_blueprint(
        default_language="da",
        communication=communication(),
        inner_ring=inner,
        outer_ring=outer_changed,
    )

    assert blueprint_sha256(first) != blueprint_sha256(second)
    assert compile_blueprint(first)["instructions"] != compile_blueprint(second)["instructions"]
    assert "Aggression=0.95" in compile_blueprint(second)["instructions"]


def test_v2_rejects_incomplete_trait_ring() -> None:
    inner, outer = trait_rings()
    del outer["meekness"]

    with pytest.raises(PersonalityBlueprintError, match="outer_ring fields"):
        build_blueprint(
            default_language="da",
            communication=communication(),
            inner_ring=inner,
            outer_ring=outer,
        )


def test_v2_requires_both_rings() -> None:
    inner, _outer = trait_rings()

    with pytest.raises(PersonalityBlueprintError, match="requires both inner_ring and outer_ring"):
        build_blueprint(
            default_language="da",
            communication=communication(),
            inner_ring=inner,
        )
