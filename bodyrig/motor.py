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
