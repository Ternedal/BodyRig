from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_reference_renderer_accepts_v1_and_v2_without_repersonalizing_performed_state() -> None:
    source = DRIVER.read_text(encoding="utf-8")

    assert "next.version != 1 && next.version != 2" in source
    assert 'ObservedEmbodimentSource = "modelrig-bodyprint-v1"' in source
    assert "next.version == 1 && next.embodiment != null" in source
    assert "next.version == 2 && next.embodiment != null" in source
    assert "ValidateObservedEmbodiment(next.embodiment.observed);" in source

    # The renderer must consume BodyRig's already-personalized performed fields.
    assert "? _state.gesture.amplitude" in source
    assert "_state.motion.head_motion" in source
    assert "_state.gaze.strength" in source
    assert "_state.speech.amplitude" in source

    # Observed v2 evidence is provenance/capability data, not another multiplier.
    late_update = source[source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")]
    assert "_state.embodiment" not in late_update
    assert "gesture_frequency" not in late_update
    assert "gesture_amplitude" not in late_update
    assert "gaze_smoothing" not in late_update
    assert "walk_cadence_spm" not in late_update


def test_reference_renderer_validates_v2_observed_ranges_but_does_not_invent_actions() -> None:
    source = DRIVER.read_text(encoding="utf-8")

    for field in (
        "energy",
        "gesture_frequency",
        "gesture_amplitude",
        "head_motion",
        "turn_speed",
        "gaze_strength",
        "head_tilt",
        "speech_motion",
        "idle_strength",
        "gaze_smoothing",
        "gesture_intensity",
        "breathing_strength",
    ):
        assert f'embodiment.observed.{field}' in source

    assert 'embodiment.observed.walk_cadence_spm' in source
    assert '300.0f' in source
    assert 'embodiment.observed.blink_rate_per_min' in source
    assert '120.0f' in source

    # Gesture semantics still come only from the performed Motor State gesture id.
    assert '_state.gesture.id == "small_shrug"' in source
    assert 'observed.gesture_frequency' not in source[source.index("private void LateUpdate()") :]
