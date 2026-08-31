from __future__ import annotations

import pytest

from bodyrig.personality_blueprint import (
    PersonalityBlueprintError,
    build_blueprint,
    compile_blueprint,
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


def test_compiler_is_deterministic_and_modelrig_ready() -> None:
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
        bodyprint=bodyprint(),
        body_revision="body-r0001",
    )

    first = compile_blueprint(value)
    second = compile_blueprint(value)
    assert first == second
    assert first["default_language"] == "da"
    assert "notably direct" in first["instructions"]
    assert "warm" in first["instructions"]
    assert "short, compact answers" in first["instructions"]
    assert "private thoughts" in first["instructions"]
    assert "movement energy=0.72" in first["style_notes"]
    assert "body revision=body-r0001" in first["style_notes"]


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
