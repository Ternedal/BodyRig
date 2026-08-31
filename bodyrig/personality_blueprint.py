from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any, Mapping

from .package import MRBodyError, validate_bodyprint

FORMAT = "bodyrig-personality-blueprint"
VERSION = 1
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")

COMMUNICATION_FIELDS = {
    "directness",
    "warmth",
    "playfulness",
    "formality",
    "verbosity",
    "initiative",
}
EMBODIMENT_FIELDS = {
    "movement_energy",
    "gesture_frequency",
    "gesture_amplitude",
    "head_motion",
    "gaze_strength",
    "speech_motion",
}
TOP_FIELDS = {
    "format",
    "version",
    "default_language",
    "communication",
    "embodiment",
    "grounding",
    "authored_notes",
}
GROUNDING_FIELDS = {"communication", "embodiment", "body_revision"}


class PersonalityBlueprintError(ValueError):
    pass


def _ratio(value: Any, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")
    return float(value)


def _text(value: Any, *, field: str, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PersonalityBlueprintError(f"{field} must be text")
    cleaned = value.strip()
    if (not empty and not cleaned) or len(cleaned) > maximum:
        raise PersonalityBlueprintError(f"{field} is invalid")
    return cleaned


def validate_blueprint(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise PersonalityBlueprintError("personality blueprint fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PersonalityBlueprintError("unsupported personality blueprint format/version")

    language = _text(value.get("default_language"), field="default_language", maximum=16)
    if LANGUAGE_RE.fullmatch(language) is None:
        raise PersonalityBlueprintError("default_language is invalid")
    communication = value.get("communication")
    embodiment = value.get("embodiment")
    grounding = value.get("grounding")
    if not isinstance(communication, Mapping) or set(communication) != COMMUNICATION_FIELDS:
        raise PersonalityBlueprintError("communication fields must match v1 exactly")
    if not isinstance(embodiment, Mapping) or set(embodiment) != EMBODIMENT_FIELDS:
        raise PersonalityBlueprintError("embodiment fields must match v1 exactly")
    if not isinstance(grounding, Mapping) or set(grounding) != GROUNDING_FIELDS:
        raise PersonalityBlueprintError("grounding fields must match v1 exactly")

    normalized_communication = {
        key: _ratio(communication[key], field=f"communication.{key}")
        for key in sorted(COMMUNICATION_FIELDS)
    }
    normalized_embodiment = {
        key: _ratio(embodiment[key], field=f"embodiment.{key}")
        for key in sorted(EMBODIMENT_FIELDS)
    }

    if grounding.get("communication") != "operator-authored":
        raise PersonalityBlueprintError(
            "communication grounding must be operator-authored; BodyRig must not infer inner personality from body/video motion"
        )
    embodiment_grounding = grounding.get("embodiment")
    if embodiment_grounding not in {"operator-authored", "bodyprint-observed", "mixed"}:
        raise PersonalityBlueprintError("embodiment grounding is invalid")
    body_revision = grounding.get("body_revision")
    if body_revision is not None:
        body_revision = _text(body_revision, field="grounding.body_revision", maximum=24)
        if BODY_REVISION_RE.fullmatch(body_revision) is None:
            raise PersonalityBlueprintError("grounding.body_revision must be a body revision id")
    if embodiment_grounding in {"bodyprint-observed", "mixed"} and body_revision is None:
        raise PersonalityBlueprintError("bodyprint-grounded embodiment requires body_revision")
    if embodiment_grounding == "operator-authored" and body_revision is not None:
        raise PersonalityBlueprintError("operator-authored embodiment must not claim a body revision grounding")

    return {
        "format": FORMAT,
        "version": VERSION,
        "default_language": language,
        "communication": normalized_communication,
        "embodiment": normalized_embodiment,
        "grounding": {
            "communication": "operator-authored",
            "embodiment": embodiment_grounding,
            "body_revision": body_revision,
        },
        "authored_notes": _text(value.get("authored_notes"), field="authored_notes", maximum=16_000, empty=True),
    }


def _bodyprint_ratio(section: Mapping[str, Any] | None, field: str, fallback: float = 0.5) -> float:
    if not isinstance(section, Mapping) or field not in section:
        return fallback
    value = section[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return fallback
    return max(0.0, min(1.0, float(value)))


def build_blueprint(
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str = "",
    bodyprint: Mapping[str, Any] | None = None,
    body_revision: str | None = None,
) -> dict[str, Any]:
    communication_values = {
        key: communication.get(key, 0.5) for key in COMMUNICATION_FIELDS
    }

    if bodyprint is None:
        if body_revision is not None:
            raise PersonalityBlueprintError("body_revision requires a bodyprint source")
        embodiment = {key: 0.5 for key in EMBODIMENT_FIELDS}
        embodiment_grounding = "operator-authored"
    else:
        if body_revision is None:
            raise PersonalityBlueprintError("bodyprint grounding requires body_revision")
        try:
            validated = validate_bodyprint(deepcopy(dict(bodyprint)))
        except (MRBodyError, TypeError, ValueError) as exc:
            raise PersonalityBlueprintError(f"bodyprint grounding is invalid: {exc}") from exc
        motion = validated.get("motion") or {}
        expression = validated.get("expression") or {}
        embodiment = {
            "movement_energy": _bodyprint_ratio(motion, "energy"),
            "gesture_frequency": _bodyprint_ratio(motion, "gesture_frequency"),
            "gesture_amplitude": _bodyprint_ratio(motion, "gesture_amplitude"),
            "head_motion": _bodyprint_ratio(motion, "head_motion"),
            "gaze_strength": _bodyprint_ratio(expression, "gaze_strength"),
            "speech_motion": _bodyprint_ratio(expression, "speech_motion"),
        }
        embodiment_grounding = "bodyprint-observed"

    return validate_blueprint({
        "format": FORMAT,
        "version": VERSION,
        "default_language": default_language,
        "communication": communication_values,
        "embodiment": embodiment,
        "grounding": {
            "communication": "operator-authored",
            "embodiment": embodiment_grounding,
            "body_revision": body_revision if bodyprint is not None else None,
        },
        "authored_notes": authored_notes,
    })


def _band(value: float, low: str, middle: str, high: str) -> str:
    if value < 0.34:
        return low
    if value > 0.66:
        return high
    return middle


def compile_blueprint(value: Mapping[str, Any] | Any) -> dict[str, str]:
    blueprint = validate_blueprint(value)
    c = blueprint["communication"]
    e = blueprint["embodiment"]

    instructions = [
        "Portray this person consistently rather than describing a persona from the outside.",
        _band(c["directness"], "Phrase things tactfully and indirectly when possible.", "Be clear and balanced in how directly you state things.", "Be notably direct and say what you mean without unnecessary hedging."),
        _band(c["warmth"], "Keep interpersonal warmth restrained and matter-of-fact.", "Use a natural, moderate level of warmth.", "Sound openly warm, personable and engaged."),
        _band(c["playfulness"], "Use little or no playful humor unless the context strongly invites it.", "Allow occasional light humor when it fits.", "Use playful or dry humor fairly often when appropriate."),
        _band(c["formality"], "Prefer casual, everyday phrasing.", "Use a conversational but composed register.", "Prefer polished and relatively formal phrasing."),
        _band(c["verbosity"], "Prefer short, compact answers.", "Use moderate detail and natural pacing.", "Give fuller answers with more context and elaboration."),
        _band(c["initiative"], "Mostly respond to what is asked instead of steering the exchange.", "Take a balanced amount of conversational initiative.", "Proactively connect ideas, ask useful follow-ups and move the exchange forward."),
        "Do not claim private thoughts, beliefs, memories, relationships or life events unless they are explicitly supplied by the active ModelRig context.",
    ]
    if blueprint["authored_notes"]:
        instructions.append("Operator-authored notes:\n" + blueprint["authored_notes"])

    style_notes = [
        "Embodiment / mannerism grounding (for compatible runtime layers):",
        f"movement energy={e['movement_energy']:.2f}",
        f"gesture frequency={e['gesture_frequency']:.2f}",
        f"gesture amplitude={e['gesture_amplitude']:.2f}",
        f"head motion={e['head_motion']:.2f}",
        f"gaze strength={e['gaze_strength']:.2f}",
        f"speech motion={e['speech_motion']:.2f}",
        f"grounding={blueprint['grounding']['embodiment']}",
    ]
    if blueprint["grounding"]["body_revision"]:
        style_notes.append(f"body revision={blueprint['grounding']['body_revision']}")

    return {
        "instructions": "\n".join(instructions),
        "default_language": blueprint["default_language"],
        "style_notes": " | ".join(style_notes),
    }
