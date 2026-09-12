from __future__ import annotations

import pytest

from bodyrig import photoidentity_openpose_runner as runner


class CountingFloat(float):
    def __new__(cls, value: float):
        instance = super().__new__(cls, value)
        instance.float_calls = 0
        return instance

    def __float__(self) -> float:
        self.float_calls += 1
        return float.__float__(self)


def _row(**updates):
    value = {
        "scene_id": "scene-a",
        "source_ordinal": 1,
        "start_seconds": 2.0,
        "duration_seconds": 6.0,
        "target_confidence": 0.95,
        "face_visibility": 0.9,
        "full_body_visibility": 0.85,
        "sharpness": 0.8,
        "occlusion": 0.1,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("start_seconds", "photoidentity row start is invalid"),
        ("duration_seconds", "photoidentity row duration is invalid"),
    ],
)
def test_candidate_selector_huge_timing_fails_with_domain_error(field, message) -> None:
    row = _row(**{field: 10**400})

    with pytest.raises(runner.PhotoIdentityOpenPoseRunnerError, match=message):
        runner.select_detail_frame_candidates([row])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_confidence", 10**400),
        ("face_visibility", True),
        ("sharpness", 10**400),
        ("occlusion", False),
    ],
)
def test_source_quality_rejects_overflow_and_boolean_values(field, value) -> None:
    with pytest.raises(runner.PhotoIdentityOpenPoseRunnerError):
        runner._score(_row(**{field: value}), face=True)


def test_candidate_selector_normalizes_timing_once_and_preserves_order() -> None:
    late_start = CountingFloat(10)
    late_duration = CountingFloat(4)
    early_start = CountingFloat(1)
    early_duration = CountingFloat(8)
    rows = [
        _row(
            start_seconds=late_start,
            duration_seconds=late_duration,
            face_visibility=0.5,
            full_body_visibility=0.95,
        ),
        _row(
            start_seconds=early_start,
            duration_seconds=early_duration,
            face_visibility=0.95,
            full_body_visibility=0.5,
        ),
    ]

    selected = runner.select_detail_frame_candidates(rows)

    assert len(selected) == 2
    assert [row["start_seconds"] for row in selected] == [1.0, 10.0]
    assert all(type(row["start_seconds"]) is float for row in selected)
    assert all(type(row["duration_seconds"]) is float for row in selected)
    assert (late_start.float_calls, late_duration.float_calls) == (1, 1)
    assert (early_start.float_calls, early_duration.float_calls) == (1, 1)
    assert rows[0]["start_seconds"] is late_start
    assert rows[0]["duration_seconds"] is late_duration


def test_candidate_selector_deduplicates_same_face_and_body_winner() -> None:
    start = CountingFloat(2)
    duration = CountingFloat(6)
    selected = runner.select_detail_frame_candidates([
        _row(start_seconds=start, duration_seconds=duration, face_visibility=0.9, full_body_visibility=0.9),
    ])

    assert len(selected) == 1
    assert selected[0]["start_seconds"] == 2.0
    assert (start.float_calls, duration.float_calls) == (1, 1)


def test_score_preserves_inclusive_unit_interval_semantics() -> None:
    assert runner._score(
        _row(target_confidence=1, face_visibility=1.0, sharpness=1, occlusion=0),
        face=True,
    ) == 1.0
    assert runner._score(
        _row(target_confidence=0, face_visibility=1.0, sharpness=1, occlusion=0),
        face=True,
    ) == 0.0
