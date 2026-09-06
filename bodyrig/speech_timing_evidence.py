from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models import SpeechTiming

FORMAT = "bodyrig-speech-timing-evidence"
VERSION = 1


class SpeechTimingEvidenceError(ValueError):
    pass


def build_speech_timing_evidence(events: Iterable[SpeechTiming | Mapping[str, Any]]) -> dict[str, Any]:
    parsed: list[SpeechTiming] = []
    for event in events:
        try:
            item = event if isinstance(event, SpeechTiming) else SpeechTiming.model_validate(event)
        except Exception as exc:
            raise SpeechTimingEvidenceError(f"speech timing event is invalid: {exc}") from exc
        parsed.append(item)
    if not 2 <= len(parsed) <= 10000:
        raise SpeechTimingEvidenceError("speech timing evidence requires 2-10000 events")
    utterance_id = parsed[0].utterance_id
    if any(item.utterance_id != utterance_id for item in parsed):
        raise SpeechTimingEvidenceError("speech timing evidence cannot mix utterance ids")
    if parsed[0].state != "start" or parsed[0].elapsed_ms != 0:
        raise SpeechTimingEvidenceError("speech timing evidence must begin with start at elapsed_ms=0")
    if parsed[-1].state != "stop" or parsed[-1].elapsed_ms <= 0:
        raise SpeechTimingEvidenceError("speech timing evidence must end with a positive stop event")
    if any(item.state != "update" for item in parsed[1:-1]):
        raise SpeechTimingEvidenceError("speech timing intermediate events must all be updates")
    elapsed = [item.elapsed_ms for item in parsed]
    if elapsed != sorted(elapsed):
        raise SpeechTimingEvidenceError("speech timing elapsed_ms must be monotonic")
    if not any(item.viseme is not None or item.amplitude is not None for item in parsed):
        raise SpeechTimingEvidenceError("speech timing evidence has no articulation signal")
    return {
        "format": FORMAT,
        "version": VERSION,
        "utterance_id": utterance_id,
        "source": "voicerig-runtime",
        "events": [
            {
                "state": item.state,
                "elapsed_ms": item.elapsed_ms,
                "viseme": item.viseme,
                "amplitude": item.amplitude,
            }
            for item in parsed
        ],
        "complete": True,
        "human_review_required": True,
        "production_activation": False,
    }
