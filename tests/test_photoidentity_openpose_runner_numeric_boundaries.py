from __future__ import annotations

import pytest

from bodyrig import photoidentity_openpose_runner as runner


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


def test_candidate_selector_normalizes_timing_once_and_preserves_ranking() -> None:
    rows = [
        _row(start_seconds=10, duration_seconds=4, face_visibility=0.5, full_body_visibility=0.95),
        _row(start_seconds=1, duration_seconds=8, face_visibility=0.95, full_body_visibility=0.5),
    ]

    selected = runner.select_detail_frame_candidates(rows)

    assert {row["start_seconds"] for row in selected} == {1.0, 10.0}
    assert all(isinstance(row["start_seconds"], float) for row in selected)
    assert all(isinstance(row["duration_seconds"], float) for row in selected)
    assert rows[0]["start_seconds"] == 10
    assert rows[0]["duration_seconds"] == 4


def test_score_preserves_inclusive_unit_interval_semantics() -> None:
    assert runner._score(
        _row(target_confidence=1, face_visibility=1.0, sharpness=1, occlusion=0),
        face=True,
    ) == 1.0
    assert runner._score(
        _row(target_confidence=0, face_visibility=1.0, sharpness=1, occlusion=0),
        face=True,
    ) == 0.0
