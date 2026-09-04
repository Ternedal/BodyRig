from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from time import time
from typing import Any, Mapping

from .models import BodyCue, SpeechTiming
from .motor import resolve_motor_state, resolve_motor_state_v2


@dataclass
class RuntimeState:
    active_body_id: str | None = None
    utterance_id: str | None = None
    cue: dict | None = None
    speech: dict | None = None
    updated_at: float = field(default_factory=time)


class BodyRuntime:
    def __init__(self) -> None:
        self._lock = RLock()
        self._state = RuntimeState()
        self._bodyprint: dict[str, Any] | None = None

    def activate(self, body_id: str, bodyprint: Mapping[str, Any] | None = None) -> RuntimeState:
        with self._lock:
            self._state.active_body_id = body_id
            self._bodyprint = deepcopy(dict(bodyprint)) if bodyprint is not None else None
            # A body switch is a session boundary. Never carry an utterance or
            # VoiceRig timing from the previously active body across it.
            self._state.utterance_id = None
            self._state.cue = None
            self._state.speech = None
            self._state.updated_at = time()
            return self.snapshot()

    def apply_cue(self, cue: BodyCue) -> RuntimeState:
        with self._lock:
            if cue.body_id is not None and self._state.active_body_id is not None and cue.body_id != self._state.active_body_id:
                raise ValueError("BodyCue body_id does not match active body")
            self._state.utterance_id = cue.utterance_id
            self._state.cue = cue.model_dump(exclude_none=True)
            self._state.speech = None
            self._state.updated_at = time()
            return self.snapshot()

    def apply_speech(self, timing: SpeechTiming) -> RuntimeState:
        with self._lock:
            if self._state.utterance_id != timing.utterance_id:
                raise ValueError("speech timing does not match active utterance")
            self._state.speech = timing.model_dump(exclude_none=True)
            self._state.updated_at = time()
            if timing.state == "stop":
                self._state.utterance_id = None
            return self.snapshot()

    def _motor_inputs(self) -> tuple[str, dict[str, Any], BodyCue, SpeechTiming | None]:
        if self._state.active_body_id is None or self._bodyprint is None:
            raise ValueError("no active body with BodyPrint")
        if self._state.cue is None:
            raise ValueError("no active BodyCue")
        cue = BodyCue.model_validate(self._state.cue)
        speech = SpeechTiming.model_validate(self._state.speech) if self._state.speech is not None else None
        return self._state.active_body_id, self._bodyprint, cue, speech

    def motor_state(self) -> dict[str, Any]:
        """Return the backwards-compatible BodyRig Motor State v1 contract."""

        with self._lock:
            body_id, bodyprint, cue, speech = self._motor_inputs()
            return resolve_motor_state(
                body_id=body_id,
                bodyprint=bodyprint,
                cue=cue,
                speech=speech,
            )

    def motor_state_v2(self) -> dict[str, Any]:
        """Return Motor State v2 with observed embodiment provenance."""

        with self._lock:
            body_id, bodyprint, cue, speech = self._motor_inputs()
            return resolve_motor_state_v2(
                body_id=body_id,
                bodyprint=bodyprint,
                cue=cue,
                speech=speech,
            )

    def snapshot(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(
                active_body_id=self._state.active_body_id,
                utterance_id=self._state.utterance_id,
                cue=dict(self._state.cue) if self._state.cue else None,
                speech=dict(self._state.speech) if self._state.speech else None,
                updated_at=self._state.updated_at,
            )
