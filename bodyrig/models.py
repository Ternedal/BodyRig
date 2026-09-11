from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BodyCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["modelrig-body-cue"] = "modelrig-body-cue"
    version: Literal[1] = 1
    utterance_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    body_id: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[a-z0-9æøå_-]+$")
    emotion: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    intensity: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    energy: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    gesture: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    gaze: str | None = None
    posture: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    duration_ms: int | None = Field(default=None, ge=0, le=120_000)

    @field_validator("gaze")
    @classmethod
    def validate_gaze(cls, value: str | None) -> str | None:
        if value is None or value in {"user", "away", "neutral"}:
            return value
        if value.startswith("object:") and 0 < len(value[7:]) <= 120:
            import re
            if re.fullmatch(r"[A-Za-z0-9._:-]+", value[7:]):
                return value
        raise ValueError("invalid gaze target")

    @model_validator(mode="after")
    def require_semantic_cue(self) -> "BodyCue":
        semantic_fields = (
            self.body_id,
            self.emotion,
            self.intensity,
            self.energy,
            self.gesture,
            self.gaze,
            self.posture,
            self.duration_ms,
        )
        if all(value is None for value in semantic_fields):
            raise ValueError("BodyCue requires at least one semantic body instruction")
        return self


class LocomotionCue(BaseModel):
    """Explicit semantic movement request.

    `effort=None` means the body's observed natural movement identity. Values
    below/above 0.5 request a bounded slower/faster performance without
    replacing the person's source-derived gait or turning style.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["walk", "turn_left", "turn_right", "stop"]
    effort: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)


class BodyCueV2(BaseModel):
    """BodyCue v2 adds explicit locomotion while leaving v1 frozen."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["modelrig-body-cue"] = "modelrig-body-cue"
    version: Literal[2] = 2
    utterance_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    body_id: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[a-z0-9æøå_-]+$")
    emotion: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    intensity: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    energy: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    gesture: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    gaze: str | None = None
    posture: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    locomotion: LocomotionCue | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=120_000)

    @field_validator("gaze")
    @classmethod
    def validate_gaze(cls, value: str | None) -> str | None:
        return BodyCue.validate_gaze(value)

    @model_validator(mode="after")
    def require_semantic_cue(self) -> "BodyCueV2":
        semantic_fields = (
            self.body_id,
            self.emotion,
            self.intensity,
            self.energy,
            self.gesture,
            self.gaze,
            self.posture,
            self.locomotion,
            self.duration_ms,
        )
        if all(value is None for value in semantic_fields):
            raise ValueError("BodyCue v2 requires at least one semantic body instruction")
        return self


BodyCueAny = BodyCue | BodyCueV2


class SpeechTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    state: Literal["start", "update", "stop"]
    elapsed_ms: int = Field(default=0, ge=0, le=3_600_000)
    viseme: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    amplitude: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
