from __future__ import annotations

from typing import Any, Mapping

from .models import BodyCue, SpeechTiming


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _number(section: Mapping[str, Any] | None, key: str, default: float) -> float:
    if not section:
        return default
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return _clamp01(float(value))


def _observed_number(
    section: Mapping[str, Any] | None,
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    """Return one actually observed BodyPrint number without inventing a default."""

    if not section or key not in section:
        return None
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not minimum <= number <= maximum:
        return None
    return number


def _observed_embodiment(bodyprint: Mapping[str, Any]) -> dict[str, float]:
    """Flatten only behavior values that are genuinely present in BodyPrint.

    Motor State v1 historically resolves several missing values through neutral
    defaults. V2 keeps that compatible performed state, but its embodiment
    receipt must never turn those defaults into claimed personal observations.
    """

    motion = bodyprint.get("motion") if isinstance(bodyprint.get("motion"), Mapping) else {}
    expression = bodyprint.get("expression") if isinstance(bodyprint.get("expression"), Mapping) else {}
    runtime = bodyprint.get("runtime") if isinstance(bodyprint.get("runtime"), Mapping) else {}

    specifications = (
        (motion, "energy", 0.0, 1.0),
        (motion, "gesture_frequency", 0.0, 1.0),
        (motion, "gesture_amplitude", 0.0, 1.0),
        (motion, "head_motion", 0.0, 1.0),
        (motion, "turn_speed", 0.0, 1.0),
        (motion, "walk_cadence_spm", 0.0, 300.0),
        (expression, "blink_rate_per_min", 0.0, 120.0),
        (expression, "gaze_strength", 0.0, 1.0),
        (expression, "head_tilt", 0.0, 1.0),
        (expression, "speech_motion", 0.0, 1.0),
        (runtime, "idle_strength", 0.0, 1.0),
        (runtime, "gaze_smoothing", 0.0, 1.0),
        (runtime, "gesture_intensity", 0.0, 1.0),
        (runtime, "breathing_strength", 0.0, 1.0),
    )

    observed: dict[str, float] = {}
    for section, key, minimum, maximum in specifications:
        value = _observed_number(section, key, minimum=minimum, maximum=maximum)
        if value is not None:
            observed[key] = value
    return observed


def resolve_motor_state(
    *,
    body_id: str,
    bodyprint: Mapping[str, Any],
    cue: BodyCue,
    speech: SpeechTiming | None = None,
) -> dict[str, Any]:
    """Resolve a semantic ModelRig cue through one body's observed style.

    This is intentionally renderer-neutral: it resolves personal amplitudes and
    behaviour strengths, not Unity bone rotations. A renderer may map the
    resulting gesture/posture ids onto its own animation system.

    This function is the frozen Motor State v1 behavior. Keep it backwards
    compatible; richer observed embodiment belongs in ``resolve_motor_state_v2``.
    """

    motion = bodyprint.get("motion") if isinstance(bodyprint.get("motion"), dict) else {}
    expression = bodyprint.get("expression") if isinstance(bodyprint.get("expression"), dict) else {}
    runtime = bodyprint.get("runtime") if isinstance(bodyprint.get("runtime"), dict) else {}

    personal_energy = _number(motion, "energy", 0.5)
    personal_gesture = _number(motion, "gesture_amplitude", 0.5)
    personal_head = _number(motion, "head_motion", 0.5)
    runtime_gesture = _number(runtime, "gesture_intensity", 0.5)
    gaze_strength = _number(expression, "gaze_strength", 0.5)
    speech_motion = _number(expression, "speech_motion", 0.5)

    requested_intensity = 0.5 if cue.intensity is None else cue.intensity
    requested_energy = personal_energy if cue.energy is None else cue.energy

    result: dict[str, Any] = {
        "type": "bodyrig-motor-state",
        "version": 1,
        "body_id": body_id,
        "utterance_id": cue.utterance_id,
        "motion": {
            "energy": _clamp01(0.55 * requested_energy + 0.45 * personal_energy),
            "head_motion": _clamp01(requested_energy * (0.5 + personal_head)),
        },
    }

    if cue.emotion is not None:
        result["expression"] = {
            "emotion": cue.emotion,
            "intensity": _clamp01(requested_intensity),
        }
    if cue.gesture is not None:
        result["gesture"] = {
            "id": cue.gesture,
            "amplitude": _clamp01(
                requested_intensity
                * (0.5 + personal_gesture)
                * (0.5 + runtime_gesture)
            ),
        }
    if cue.gaze is not None:
        result["gaze"] = {
            "target": cue.gaze,
            "strength": gaze_strength,
        }
    if cue.posture is not None:
        result["posture"] = {
            "id": cue.posture,
            "intensity": _clamp01(requested_intensity),
        }
    if cue.duration_ms is not None:
        result["duration_ms"] = cue.duration_ms

    if speech is not None and speech.utterance_id == cue.utterance_id:
        speech_result: dict[str, Any] = {
            "state": speech.state,
            "elapsed_ms": speech.elapsed_ms,
        }
        if speech.viseme is not None:
            speech_result["viseme"] = speech.viseme
        if speech.amplitude is not None:
            # speech_motion is a per-body expressivity multiplier. A quiet body
            # profile still articulates; it simply uses less head/jaw energy.
            speech_result["amplitude"] = _clamp01(speech.amplitude * (0.5 + speech_motion))
        result["speech"] = speech_result

    return result


def resolve_motor_state_v2(
    *,
    body_id: str,
    bodyprint: Mapping[str, Any],
    cue: BodyCue,
    speech: SpeechTiming | None = None,
) -> dict[str, Any]:
    """Resolve Motor State v2 without changing v1 performance semantics.

    V2 carries an additional renderer-neutral receipt of *actually observed*
    BodyPrint behavior values. Missing BodyPrint fields are omitted instead of
    being synthesized as personal identity/style facts.
    """

    result = resolve_motor_state(
        body_id=body_id,
        bodyprint=bodyprint,
        cue=cue,
        speech=speech,
    )
    result["version"] = 2

    observed = _observed_embodiment(bodyprint)
    if observed:
        result["embodiment"] = {
            "source": "modelrig-bodyprint-v1",
            "observed": observed,
        }
    return result
