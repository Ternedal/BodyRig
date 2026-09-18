from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .package import MRBodyError, validate_bodyprint

FORMAT = "bodyrig-personality-blueprint"
LEGACY_VERSION = 1
VERSION = 2
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
V1_TOP_FIELDS = {
    "format",
    "version",
    "default_language",
    "communication",
    "embodiment",
    "grounding",
    "style_exemplars",
    "authored_notes",
}
V2_TOP_FIELDS = V1_TOP_FIELDS | {"inner_ring", "outer_ring"}
TOP_FIELDS = V1_TOP_FIELDS
GROUNDING_FIELDS = {"communication", "embodiment", "body_revision"}

INNER_RING_TRAITS = (
    ("bulk_apperception", "Bulk Apperception"),
    ("candor", "Candor"),
    ("coordination", "Coordination"),
    ("vindictiveness", "Vindictiveness"),
    ("stubbornness", "Stubbornness"),
    ("innovation", "Innovation"),
    ("kindness", "Kindness"),
    ("assurance", "Assurance"),
    ("facility", "Facility"),
    ("meticulousness", "Meticulousness"),
    ("capriciousness", "Capriciousness"),
    ("fastidiousness", "Fastidiousness"),
    ("rhythm", "Rhythm"),
    ("hubris", "Hubris"),
    ("fragility", "Fragility"),
    ("leadership", "Leadership"),
    ("education", "Education"),
    ("wisdom", "Wisdom"),
    ("entitlement", "Entitlement"),
    ("individualism", "Individualism"),
    ("laziness", "Laziness"),
    ("forgetfulness", "Forgetfulness"),
    ("tenderness", "Tenderness"),
    ("masculinity", "Masculinity"),
    ("expressivity", "Expressivity"),
    ("fashionableness", "Fashionableness"),
    ("fidelity", "Fidelity"),
    ("spirituality", "Spirituality"),
    ("patriotism", "Patriotism"),
    ("brusqueness", "Brusqueness"),
    ("whimsy", "Whimsy"),
    ("introversion", "Introversion"),
    ("strength", "Strength"),
    ("competitiveness", "Competitiveness"),
    ("pride", "Pride"),
    ("consideration", "Consideration"),
    ("congeniality", "Congeniality"),
    ("literalism", "Literalism"),
    ("confidence", "Confidence"),
    ("courtesy", "Courtesy"),
    ("morality", "Morality"),
    ("artistry", "Artistry"),
    ("faith", "Faith"),
    ("bellicosity", "Bellicosity"),
    ("reserve", "Reserve"),
    ("gentleness", "Gentleness"),
    ("integrity", "Integrity"),
    ("sarcasm", "Sarcasm"),
    ("wanderlust", "Wanderlust"),
    ("timidity", "Timidity"),
    ("sociopathy", "Sociopathy"),
    ("intuition", "Intuition"),
    ("humor", "Humor"),
    ("sensuality", "Sensuality"),
    ("tenacity", "Tenacity"),
    ("loyalty", "Loyalty"),
    ("curiosity", "Curiosity"),
    ("decisiveness", "Decisiveness"),
    ("self_preservation", "Self-Preservation"),
    ("humility", "Humility"),
)

OUTER_RING_TRAITS = (
    ("vivacity", "Vivacity"),
    ("coordination", "Coordination"),
    ("generosity", "Generosity"),
    ("narcissism", "Narcissism"),
    ("lugubriousness", "Lugubriousness"),
    ("adventurousness", "Adventurousness"),
    ("articulateness", "Articulateness"),
    ("poise", "Poise"),
    ("paternalism", "Paternalism"),
    ("delicacy", "Delicacy"),
    ("cleanliness", "Cleanliness"),
    ("health", "Health"),
    ("self_esteem", "Self-Esteem"),
    ("wonderment", "Wonderment"),
    ("deceptiveness", "Deceptiveness"),
    ("willingness", "Willingness"),
    ("knowledgeableness", "Knowledgeableness"),
    ("judiciousness", "Judiciousness"),
    ("sexuality", "Sexuality"),
    ("selfishness", "Selfishness"),
    ("industry", "Industry"),
    ("affection", "Affection"),
    ("femininity", "Femininity"),
    ("flexibility", "Flexibility"),
    ("reflectiveness", "Reflectiveness"),
    ("decorum", "Decorum"),
    ("skepticism", "Skepticism"),
    ("inhibition", "Inhibition"),
    ("reticence", "Reticence"),
    ("stoicism", "Stoicism"),
    ("extroversion", "Extroversion"),
    ("restraint", "Restraint"),
    ("physicality", "Physicality"),
    ("passivity", "Passivity"),
    ("comprehensiveness", "Comprehensiveness"),
    ("gregariousness", "Gregariousness"),
    ("determination", "Determination"),
    ("visionariness", "Visionariness"),
    ("joy", "Joy"),
    ("focus", "Focus"),
    ("musicality", "Musicality"),
    ("obedience", "Obedience"),
    ("endurance", "Endurance"),
    ("ribaldry", "Ribaldry"),
    ("perseverance", "Perseverance"),
    ("peacefulness", "Peacefulness"),
    ("grit", "Grit"),
    ("temperance", "Temperance"),
    ("brazenness", "Brazenness"),
    ("egocentricism", "Egocentricism"),
    ("emotional_acuity", "Emotional Acuity"),
    ("perception", "Perception"),
    ("charm", "Charm"),
    ("courage", "Courage"),
    ("empathy", "Empathy"),
    ("aggression", "Aggression"),
    ("imagination", "Imagination"),
    ("patience", "Patience"),
    ("cruelty", "Cruelty"),
    ("meekness", "Meekness"),
)


class PersonalityBlueprintError(ValueError):
    pass


def _ratio(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")
    try:
        numeric = float(value)
    except OverflowError:
        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1") from None
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise PersonalityBlueprintError(f"{field} must be a finite number in 0..1")
    return numeric


def _text(value: Any, *, field: str, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PersonalityBlueprintError(f"{field} must be text")
    cleaned = value.strip()
    if (not empty and not cleaned) or len(cleaned) > maximum:
        raise PersonalityBlueprintError(f"{field} is invalid")
    return cleaned


def _style_exemplars(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
        raise PersonalityBlueprintError("style_exemplars must be a list with at most 12 items")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _text(item, field=f"style_exemplars[{index}]", maximum=1000)
        key = text.casefold()
        if key in seen:
            raise PersonalityBlueprintError("style_exemplars must be unique")
        seen.add(key)
        result.append(text)
    return result


def personality_trait_definitions() -> dict[str, Any]:
    return {
        "format": "bodyrig-personality-trait-matrix-definition",
        "version": VERSION,
        "scale": {"minimum": 0.0, "neutral": 0.5, "maximum": 1.0},
        "rings": {
            "inner": [
                {"id": trait_id, "label": label, "order": index}
                for index, (trait_id, label) in enumerate(INNER_RING_TRAITS, start=1)
            ],
            "outer": [
                {"id": trait_id, "label": label, "order": index}
                for index, (trait_id, label) in enumerate(OUTER_RING_TRAITS, start=1)
            ],
        },
    }


def _trait_ring(
    value: Any,
    *,
    ring: str,
    definitions: Sequence[tuple[str, str]],
) -> dict[str, float]:
    expected = {trait_id for trait_id, _label in definitions}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PersonalityBlueprintError(
            f"{ring}_ring fields must match personality blueprint v2 exactly"
        )
    return {
        trait_id: _ratio(value[trait_id], field=f"{ring}_ring.{trait_id}")
        for trait_id, _label in definitions
    }


def validate_blueprint(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PersonalityBlueprintError("personality blueprint must be an object")

    raw_version = value.get("version")
    if (
        value.get("format") != FORMAT
        or isinstance(raw_version, bool)
        or not isinstance(raw_version, (int, float))
        or raw_version not in {LEGACY_VERSION, VERSION}
    ):
        raise PersonalityBlueprintError("unsupported personality blueprint format/version")
    version = int(raw_version)
    expected_fields = V1_TOP_FIELDS if version == LEGACY_VERSION else V2_TOP_FIELDS
    if set(value) != expected_fields:
        raise PersonalityBlueprintError(
            f"personality blueprint fields must match v{version} exactly"
        )

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

    normalized = {
        "format": FORMAT,
        "version": version,
        "default_language": language,
        "communication": normalized_communication,
        "embodiment": normalized_embodiment,
        "grounding": {
            "communication": "operator-authored",
            "embodiment": embodiment_grounding,
            "body_revision": body_revision,
        },
        "style_exemplars": _style_exemplars(value.get("style_exemplars")),
        "authored_notes": _text(
            value.get("authored_notes"),
            field="authored_notes",
            maximum=16_000,
            empty=True,
        ),
    }
    if version == VERSION:
        normalized["inner_ring"] = _trait_ring(
            value.get("inner_ring"),
            ring="inner",
            definitions=INNER_RING_TRAITS,
        )
        normalized["outer_ring"] = _trait_ring(
            value.get("outer_ring"),
            ring="outer",
            definitions=OUTER_RING_TRAITS,
        )
    return normalized

def blueprint_sha256(value: Mapping[str, Any] | Any) -> str:
    blueprint = validate_blueprint(value)
    encoded = json.dumps(
        blueprint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    style_exemplars: Sequence[str] | None = None,
    bodyprint: Mapping[str, Any] | None = None,
    body_revision: str | None = None,
    inner_ring: Mapping[str, Any] | None = None,
    outer_ring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    communication_values = {
        key: communication.get(key, 0.5) for key in COMMUNICATION_FIELDS
    }

    if (inner_ring is None) != (outer_ring is None):
        raise PersonalityBlueprintError(
            "personality blueprint v2 requires both inner_ring and outer_ring"
        )
    version = VERSION if inner_ring is not None else LEGACY_VERSION

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

    payload: dict[str, Any] = {
        "format": FORMAT,
        "version": version,
        "default_language": default_language,
        "communication": communication_values,
        "embodiment": embodiment,
        "grounding": {
            "communication": "operator-authored",
            "embodiment": embodiment_grounding,
            "body_revision": body_revision if bodyprint is not None else None,
        },
        "style_exemplars": list(style_exemplars or []),
        "authored_notes": authored_notes,
    }
    if version == VERSION:
        payload["inner_ring"] = dict(inner_ring or {})
        payload["outer_ring"] = dict(outer_ring or {})
    return validate_blueprint(payload)

def _band(value: float, low: str, middle: str, high: str) -> str:
    if value < 0.34:
        return low
    if value > 0.66:
        return high
    return middle


def _trait_instruction_line(
    label: str,
    values: Mapping[str, float],
    definitions: Sequence[tuple[str, str]],
) -> str:
    encoded = "; ".join(
        f"{trait_label}={json.dumps(values[trait_id], allow_nan=False)}"
        for trait_id, trait_label in definitions
    )
    return f"{label}: {encoded}"


def compile_blueprint(value: Mapping[str, Any] | Any) -> dict[str, str]:
    blueprint = validate_blueprint(value)
    digest = blueprint_sha256(blueprint)
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
    if blueprint["version"] == VERSION:
        instructions.extend(
            [
                "Use the following explicit operator-authored personality trait matrix as behavioral tendencies. Values are normalized from 0.0 (low) to 1.0 (high), with 0.5 neutral. Do not reinterpret trait values as biography, memory, relationships, beliefs or factual claims.",
                _trait_instruction_line(
                    "Inner ring",
                    blueprint["inner_ring"],
                    INNER_RING_TRAITS,
                ),
                _trait_instruction_line(
                    "Outer ring",
                    blueprint["outer_ring"],
                    OUTER_RING_TRAITS,
                ),
            ]
        )
    if blueprint["style_exemplars"]:
        instructions.extend([
            "The following operator-approved utterances are style exemplars only. Imitate their phrasing, rhythm and conversational texture when useful, but do not treat their factual content as current truth, biography or memory:",
            *[f"- {text}" for text in blueprint["style_exemplars"]],
        ])
    if blueprint["authored_notes"]:
        instructions.append("Operator-authored notes:\n" + blueprint["authored_notes"])

    style_notes = [
        f"blueprint_sha256={digest}",
        f"style_exemplars={len(blueprint['style_exemplars'])}",
        "Embodiment / mannerism grounding (for compatible runtime layers):",
        f"movement energy={e['movement_energy']:.2f}",
        f"gesture frequency={e['gesture_frequency']:.2f}",
        f"gesture amplitude={e['gesture_amplitude']:.2f}",
        f"head motion={e['head_motion']:.2f}",
        f"gaze strength={e['gaze_strength']:.2f}",
        f"speech motion={e['speech_motion']:.2f}",
        f"grounding={blueprint['grounding']['embodiment']}",
    ]
    if blueprint["version"] == VERSION:
        style_notes.extend(
            [
                "trait matrix=v2",
                f"inner ring traits={len(INNER_RING_TRAITS)}",
                f"outer ring traits={len(OUTER_RING_TRAITS)}",
            ]
        )
    if blueprint["grounding"]["body_revision"]:
        style_notes.append(f"body revision={blueprint['grounding']['body_revision']}")

    return {
        "instructions": "\n".join(instructions),
        "default_language": blueprint["default_language"],
        "style_notes": " | ".join(style_notes),
    }

