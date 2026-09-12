from __future__ import annotations

from bodyrig.models import BodyCue
from bodyrig.motor import _number, _observed_number
from bodyrig.runtime import BodyRuntime


class CountingInt(int):
    def __new__(cls, value: int):
        instance = int.__new__(cls, value)
        instance.float_calls = 0
        return instance

    def __float__(self) -> float:
        self.float_calls += 1
        return float(int(self))


def test_legacy_numeric_helpers_normalize_overflow_to_existing_tolerant_semantics() -> None:
    huge = 10**400

    assert _number({"energy": huge}, "energy", 0.5) == 0.5
    assert _observed_number({"energy": huge}, "energy", minimum=0.0, maximum=1.0) is None


def test_legacy_numeric_helpers_preserve_boolean_type_and_range_behavior() -> None:
    assert _number({"energy": True}, "energy", 0.5) == 0.5
    assert _number({"energy": "0.25"}, "energy", 0.5) == 0.5
    assert _number({"energy": 2}, "energy", 0.5) == 1.0
    assert _number({"energy": 0.25}, "energy", 0.5) == 0.25

    assert _observed_number({"energy": True}, "energy", minimum=0.0, maximum=1.0) is None
    assert _observed_number({"energy": "0.25"}, "energy", minimum=0.0, maximum=1.0) is None
    assert _observed_number({"energy": 2}, "energy", minimum=0.0, maximum=1.0) is None
    assert _observed_number({"energy": 0.25}, "energy", minimum=0.0, maximum=1.0) == 0.25


def test_number_converts_accepted_bodyprint_numeric_exactly_once() -> None:
    value = CountingInt(1)

    assert _number({"energy": value}, "energy", 0.5) == 1.0
    assert value.float_calls == 1


def test_runtime_v1_uses_neutral_fallback_for_huge_legacy_bodyprint_numeric() -> None:
    runtime = BodyRuntime()
    runtime.activate(
        "person-a",
        {
            "format": "modelrig-bodyprint",
            "version": 1,
            "motion": {"energy": 10**400},
        },
    )
    runtime.apply_cue(BodyCue(utterance_id="u-overflow", energy=0.5))

    state = runtime.motor_state()

    assert state["version"] == 1
    assert state["motion"] == {"energy": 0.5, "head_motion": 0.5}


def test_runtime_v2_omits_huge_numeric_from_observed_embodiment() -> None:
    runtime = BodyRuntime()
    runtime.activate(
        "person-a",
        {
            "format": "modelrig-bodyprint",
            "version": 1,
            "motion": {
                "energy": 10**400,
                "gesture_frequency": 0.4,
            },
        },
    )
    runtime.apply_cue(BodyCue(utterance_id="u-overflow-v2", energy=0.5))

    state = runtime.motor_state_v2()

    assert state["version"] == 2
    assert state["motion"] == {"energy": 0.5, "head_motion": 0.5}
    assert state["embodiment"] == {
        "source": "modelrig-bodyprint-v1",
        "observed": {"gesture_frequency": 0.4},
    }
