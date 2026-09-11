from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
MOTOR_V2 = REPO / "contracts" / "bodyrig-motor-state-v2.schema.json"


def _observed_schema_fields() -> set[str]:
    contract = json.loads(MOTOR_V2.read_text(encoding="utf-8"))
    return set(
        contract["properties"]["embodiment"]["properties"]["observed"]["properties"]
    )


def _observed_driver_fields(source: str) -> set[str]:
    start = source.index("private sealed class ObservedEmbodimentState")
    end = source.index("private sealed class EmbodimentState", start)
    block = source[start:end]
    return set(re.findall(r"public float ([A-Za-z0-9_]+);", block))


def test_reference_renderer_keeps_v1_v2_compatibility_without_repersonalizing_performed_state() -> None:
    source = DRIVER.read_text(encoding="utf-8")

    assert "next.version != 1 && next.version != 2 && next.version != 3" in source
    assert 'ObservedEmbodimentSource = "modelrig-bodyprint-v1"' in source
    assert "next.version == 1 && next.embodiment != null" in source
    assert "next.version >= 2 && next.embodiment != null" in source
    assert "ValidateObservedEmbodiment(next.embodiment.observed);" in source
    assert "next.version < 3 && next.locomotion != null" in source

    # The renderer must consume BodyRig's already-personalized performed fields.
    assert "? _state.gesture.amplitude" in source
    assert "_state.motion.head_motion" in source
    assert "_state.gaze.strength" in source
    assert "_state.speech.amplitude" in source

    # Raw observed evidence is provenance/capability data, not another multiplier
    # and, critically, must never create an unsolicited movement/posture action.
    late_update = source[source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")]
    assert "_state.embodiment" not in late_update
    assert ".embodiment.observed" not in late_update
    for field in (
        "walk_cadence_spm",
        "posture_torso_lean_degrees",
        "posture_torso_forward_lean_degrees",
        "posture_torso_right_lean_degrees",
        "posture_shoulder_tilt_degrees",
        "posture_shoulder_roll_degrees",
        "posture_hip_tilt_degrees",
        "posture_hip_roll_degrees",
        "posture_head_offset_to_height",
        "posture_head_forward_offset_to_height",
        "posture_head_right_offset_to_height",
        "arm_swing_asymmetry",
        "idle_sway_to_height",
    ):
        assert field not in late_update


def test_reference_renderer_deserializes_every_v2_observed_embodiment_field() -> None:
    source = DRIVER.read_text(encoding="utf-8")

    # JsonUtility silently ignores unknown JSON members. Keep the C# DTO in
    # exact parity with the canonical schema so newly recovered movement
    # identity evidence cannot disappear at the renderer boundary.
    assert _observed_driver_fields(source) == _observed_schema_fields()


def test_reference_renderer_validates_every_v2_observed_range_but_does_not_invent_actions() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    start = source.index("private static void ValidateObservedEmbodiment")
    end = source.index("private static void Validate01", start)
    validation = source[start:end]

    for field in sorted(_observed_schema_fields()):
        assert f"observed.{field}" in validation
        assert f'embodiment.observed.{field}' in validation

    # Non-0..1 and signed movement ranges stay explicit rather than being
    # accidentally clamped into generic style values.
    assert 'ValidateRange(observed.walk_cadence_spm, 0.0f, 300.0f' in validation
    assert 'ValidateRange(observed.posture_torso_lean_degrees, 0.0f, 90.0f' in validation
    assert 'ValidateRange(observed.posture_torso_forward_lean_degrees, -90.0f, 90.0f' in validation
    assert 'ValidateRange(observed.posture_torso_right_lean_degrees, -90.0f, 90.0f' in validation
    assert 'ValidateRange(observed.posture_shoulder_roll_degrees, -90.0f, 90.0f' in validation
    assert 'ValidateRange(observed.posture_hip_roll_degrees, -90.0f, 90.0f' in validation
    assert 'ValidateRange(observed.posture_head_forward_offset_to_height, -1.0f, 1.0f' in validation
    assert 'ValidateRange(observed.posture_head_right_offset_to_height, -1.0f, 1.0f' in validation
    assert 'ValidateRange(observed.stride_length_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(observed.arm_swing_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(observed.turn_speed_degrees_per_second, 0.0f, 720.0f' in validation
    assert 'ValidateRange(observed.blink_rate_per_min, 0.0f, 120.0f' in validation

    # Gesture semantics still come only from the performed Motor State gesture id.
    assert '_state.gesture.id == "small_shrug"' in source
