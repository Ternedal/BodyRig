from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
MOTOR_V3 = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _locomotion_schema_fields() -> set[str]:
    contract = json.loads(MOTOR_V3.read_text(encoding="utf-8"))
    variants = contract["properties"]["locomotion"]["oneOf"]
    return set().union(*(set(item["properties"]) for item in variants))


def _locomotion_driver_fields(source: str) -> set[str]:
    start = source.index("private sealed class LocomotionState")
    end = source.index("private sealed class SpeechState", start)
    block = source[start:end]
    return set(re.findall(r"public (?:float|string) ([A-Za-z0-9_]+);", block))


def test_reference_renderer_v3_dto_matches_performed_locomotion_contract() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert _locomotion_driver_fields(source) == _locomotion_schema_fields()
    assert "public LocomotionState locomotion;" in source
    assert "LocomotionRealized = ApplyLocomotion(dt);" in source
    assert "public bool LocomotionRealized" in source


def test_reference_renderer_v3_validates_action_specific_performed_ranges() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    start = source.index("private static void ValidateLocomotion")
    end = source.index("private static void ValidateObservedEmbodiment", start)
    validation = source[start:end]

    for action in ("walk", "turn_left", "turn_right", "stop"):
        assert f'"{action}"' in validation
    assert 'ValidateRange(locomotion.cadence_spm, 30.0f, 240.0f' in validation
    assert 'ValidateRange(locomotion.stride_length_to_height, 0.0f, 2.0f' in validation
    assert 'Validate01(locomotion.stance_width_to_height' in validation
    assert 'Validate01(locomotion.vertical_bounce_to_height' in validation
    assert 'ValidateRange(locomotion.arm_swing_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f' in validation


def test_reference_renderer_realizes_only_performed_locomotion_not_raw_evidence() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    start = source.index("private bool ApplyLocomotion")
    end = source.index("private bool ApplyGesture", start)
    realization = source[start:end]

    assert "_state.embodiment" not in realization
    assert ".observed" not in realization
    assert "_state.locomotion" in realization
    assert "locomotion.cadence_spm / 120.0f" in realization
    assert "locomotion.stride_length_to_height" in realization
    assert "locomotion.stance_width_to_height" in realization
    assert "locomotion.vertical_bounce_to_height" in realization
    assert "locomotion.arm_swing_to_height" in realization
    assert "locomotion.turn_speed_degrees_per_second * dt" in realization

    # A walk cue has no destination/distance. The reference gait is therefore
    # in-place; only explicit turn actions are allowed to mutate root heading.
    assert ".Translate(" not in realization
    assert ".position +=" not in realization
    assert "transform.Rotate(" in realization
    assert 'locomotion.action == "turn_left"' in realization
    assert 'locomotion.action == "turn_right"' in realization


def test_reference_renderer_walk_requires_real_humanoid_height_and_leg_bones() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    start = source.index("private bool ApplyLocomotion")
    end = source.index("private bool ApplyGesture", start)
    realization = source[start:end]

    assert "_leftUpperLeg == null" in realization
    assert "_rightUpperLeg == null" in realization
    assert "_leftLowerLeg == null" in realization
    assert "_rightLowerLeg == null" in realization
    assert "_avatarHeight <= 0.0001f" in realization
    assert "return false;" in realization
    assert "_avatarHeight = 1.7" not in source


def test_reference_renderer_does_not_let_old_motor_versions_smuggle_locomotion() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert "next.version < 3 && next.locomotion != null" in source
    assert 'throw new ArgumentException("Motor State v1/v2 may not carry locomotion"' in source
