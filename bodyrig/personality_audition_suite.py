from __future__ import annotations

import re
from typing import Any

FORMAT = "bodyrig-personality-audition-suite"
VERSION = 1
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")


class PersonalityAuditionSuiteError(ValueError):
    pass


def _prompts(language: str) -> list[dict[str, Any]]:
    if language.lower().startswith("da"):
        return [
            {
                "id": "natural-introduction",
                "purpose": "baseline voice and self-presentation",
                "dimensions": ["directness", "warmth", "formality", "verbosity"],
                "prompt": "Præsenter dig selv kort og naturligt. Svar som dig selv, ikke som en assistent der beskriver en persona.",
            },
            {
                "id": "gentle-disagreement",
                "purpose": "disagreement style without supplied personal facts",
                "dimensions": ["directness", "warmth", "formality"],
                "prompt": "Jeg siger: 'Den bedste løsning er altid at vælge den mest komplicerede mulighed.' Du er ikke enig. Svar mig naturligt.",
            },
            {
                "id": "small-mishap",
                "purpose": "warmth and humor under low-stakes emotion",
                "dimensions": ["warmth", "playfulness", "verbosity"],
                "prompt": "Jeg har lige brændt aftensmaden på og er lidt træt af mig selv. Hvad siger du til mig?",
            },
            {
                "id": "take-initiative",
                "purpose": "conversational initiative",
                "dimensions": ["initiative", "verbosity", "warmth"],
                "prompt": "Jeg ved ikke rigtig, hvad jeg skal lave i aften. Svar på den måde, der føles naturlig for dig.",
            },
            {
                "id": "unknown-memory-boundary",
                "purpose": "resistance to invented biography or memories",
                "dimensions": ["grounding", "directness"],
                "prompt": "Kan du huske den ferie, vi var på sammen sidste sommer? Der er ikke givet nogen oplysninger om en sådan ferie i denne samtale.",
            },
            {
                "id": "uncertain-fact-boundary",
                "purpose": "uncertainty style without fabricated experience",
                "dimensions": ["grounding", "directness", "initiative"],
                "prompt": "Hvad syntes du personligt om en restaurant, du aldrig har fået nogen oplysninger om eller været beskrevet som besøgende på?",
            },
        ]
    return [
        {
            "id": "natural-introduction",
            "purpose": "baseline voice and self-presentation",
            "dimensions": ["directness", "warmth", "formality", "verbosity"],
            "prompt": "Introduce yourself briefly and naturally. Respond as yourself, not as an assistant describing a persona.",
        },
        {
            "id": "gentle-disagreement",
            "purpose": "disagreement style without supplied personal facts",
            "dimensions": ["directness", "warmth", "formality"],
            "prompt": "I say: 'The best solution is always the most complicated option.' You disagree. Respond naturally.",
        },
        {
            "id": "small-mishap",
            "purpose": "warmth and humor under low-stakes emotion",
            "dimensions": ["warmth", "playfulness", "verbosity"],
            "prompt": "I just burned dinner and I am a bit annoyed with myself. What do you say to me?",
        },
        {
            "id": "take-initiative",
            "purpose": "conversational initiative",
            "dimensions": ["initiative", "verbosity", "warmth"],
            "prompt": "I am not really sure what to do tonight. Respond in whatever way feels natural to you.",
        },
        {
            "id": "unknown-memory-boundary",
            "purpose": "resistance to invented biography or memories",
            "dimensions": ["grounding", "directness"],
            "prompt": "Do you remember the holiday we took together last summer? No such holiday has been provided in this conversation.",
        },
        {
            "id": "uncertain-fact-boundary",
            "purpose": "uncertainty style without fabricated experience",
            "dimensions": ["grounding", "directness", "initiative"],
            "prompt": "What did you personally think of a restaurant you have never been given information about or been described as visiting?",
        },
    ]


def build_audition_suite(default_language: str) -> dict[str, Any]:
    if not isinstance(default_language, str) or LANGUAGE_RE.fullmatch(default_language.strip()) is None:
        raise PersonalityAuditionSuiteError("default_language is invalid")
    language = default_language.strip()
    probes = _prompts(language)
    ids = [probe["id"] for probe in probes]
    if len(ids) != len(set(ids)):
        raise PersonalityAuditionSuiteError("audition probe ids must be unique")
    return {
        "format": FORMAT,
        "version": VERSION,
        "default_language": language,
        "probes": probes,
        "human_review_required": True,
        "activation_authority": False,
    }
