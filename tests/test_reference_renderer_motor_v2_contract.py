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
        "left_arm_swing_to_height",
        "right_arm_swing_to_height",
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
    assert 'ValidateRange(observed.left_arm_swing_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(observed.right_arm_swing_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(observed.arm_swing_to_height, 0.0f, 2.0f' in validation
    assert 'ValidateRange(observed.turn_speed_degrees_per_second, 0.0f, 720.0f' in validation
    assert 'ValidateRange(observed.blink_rate_per_min, 0.0f, 120.0f' in validation

    # Gesture semantics still come only from the performed Motor State gesture id.
    assert '_state.gesture.id == "small_shrug"' in source


def test_reference_renderer_affect_transition_clears_previous_emotion_without_touching_visemes() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply_expression = source[source.index("private bool ApplyExpression") : source.index("private bool ApplySpeech")]

    # Unsupported semantic ids fail before any renderer channel is mutated.
    support_switch = apply_expression.index("switch (_state.expression.emotion)")
    first_clear = apply_expression.index("expression.SetWeight(ExpressionKey.Neutral, 0.0f);")
    assert support_switch < first_clear
    assert "default:\n                    return false;" in apply_expression[support_switch:first_clear]

    for key in ("Neutral", "Happy", "Angry", "Sad", "Relaxed", "Surprised"):
        assert f"expression.SetWeight(ExpressionKey.{key}, 0.0f);" in apply_expression

    # Affect cleanup must not erase simultaneous speech articulation.
    for viseme in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"ExpressionKey.{viseme}" not in apply_expression

    weight = apply_expression.index("var weight = Mathf.Clamp01(_state.expression.intensity);")
    apply_switch = apply_expression.index("switch (_state.expression.emotion)", support_switch + 1)
    assert first_clear < weight < apply_switch
    for emotion, key in (
        ("neutral", "Neutral"),
        ("happy", "Happy"),
        ("angry", "Angry"),
        ("sad", "Sad"),
        ("relaxed", "Relaxed"),
        ("surprised", "Surprised"),
    ):
        assert f'case "{emotion}": expression.SetWeight(ExpressionKey.{key}, weight); return true;' in apply_expression


def test_reference_renderer_viseme_transition_clears_previous_shape_without_touching_affect() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply_speech = source[source.index("private bool ApplySpeech") : source.index("private void RestoreGesturePose")]

    # An explicit speech stop owns the viseme channel even when viseme is omitted.
    stop_start = apply_speech.index('if (_state.speech.state == "stop")')
    blank_guard = apply_speech.index("if (string.IsNullOrWhiteSpace(_state.speech.viseme))")
    stop = apply_speech[stop_start:blank_guard]
    assert stop_start < blank_guard
    for key in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"expression.SetWeight(ExpressionKey.{key}, 0.0f);" in stop
    assert "return true;" in stop

    # Affect is a separate simultaneously-owned channel and must not be reset by speech.
    for affect in ("Neutral", "Happy", "Angry", "Sad", "Relaxed", "Surprised"):
        assert f"ExpressionKey.{affect}" not in apply_speech

    assert "var viseme = _state.speech.viseme.ToUpperInvariant();" in apply_speech
    support_switch = apply_speech.index("switch (viseme)")
    regular_clear = apply_speech.index("expression.SetWeight(ExpressionKey.Aa, 0.0f);", support_switch)
    assert support_switch < regular_clear
    assert "default:\n                    return false;" in apply_speech[support_switch:regular_clear]

    # A supported start/update clears stale shapes before setting exactly one new shape.
    for key in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"expression.SetWeight(ExpressionKey.{key}, 0.0f);" in apply_speech[regular_clear:]
    weight = apply_speech.index("var weight = Mathf.Clamp01(_speechAmplitude);")
    apply_switch = apply_speech.index("switch (viseme)", support_switch + 1)
    assert regular_clear < weight < apply_switch
    for viseme, key in (("AA", "Aa"), ("IH", "Ih"), ("OU", "Ou"), ("EE", "Ee"), ("OH", "Oh")):
        assert f'case "{viseme}": expression.SetWeight(ExpressionKey.{key}, weight); return true;' in apply_speech
