from __future__ import annotations

import pytest

from bodyrig.observation import Observation, ObservationError, select_observations


def _observation(
    source_id: str,
    start: float,
    *,
    face: float,
    body: float,
    base_score: float,
    view: str = "front",
) -> Observation:
    return Observation(
        source_id=source_id,
        start_seconds=start,
        duration_seconds=6.0,
        target_confidence=0.9,
        target_screen_fraction=0.6,
        face_visibility=face,
        full_body_visibility=body,
        sharpness=0.9,
        occlusion=0.05,
        motion=0.3,
        view=view,
        base_score=base_score,
    )


def test_selection_fails_closed_when_quality_pool_has_no_face_strong_observation() -> None:
    observations = [
        _observation("s001", 0.0, face=0.71, body=0.95, base_score=0.90),
        _observation("s002", 10.0, face=0.99, body=0.40, base_score=0.20),
    ]

    with pytest.raises(ObservationError, match="no face-strong observation"):
        select_observations(observations, min_base_score=0.35)


def test_selection_fails_closed_when_quality_pool_has_no_full_body_strong_observation() -> None:
    observations = [
        _observation("s001", 0.0, face=0.95, body=0.71, base_score=0.90),
        _observation("s002", 10.0, face=0.40, body=0.99, base_score=0.20),
    ]

    with pytest.raises(ObservationError, match="no full-body-strong observation"):
        select_observations(observations, min_base_score=0.35)


def test_mandatory_face_and_body_coverage_outranks_higher_scoring_generic_window() -> None:
    generic = _observation("s001", 0.0, face=0.71, body=0.71, base_score=0.99, view="rear")
    face = _observation("s002", 10.0, face=0.95, body=0.45, base_score=0.80, view="front")
    body = _observation("s003", 20.0, face=0.45, body=0.95, base_score=0.79, view="left_profile")

    selected = select_observations(
        [generic, face, body],
        max_segments=2,
        min_base_score=0.35,
        max_per_source=2,
    )

    assert {item.source_id for item in selected} == {"s002", "s003"}
    assert all(item is not generic for item in selected)


def test_single_dual_coverage_window_can_satisfy_one_segment_budget() -> None:
    dual = _observation("s001", 0.0, face=0.90, body=0.90, base_score=0.75)
    generic = _observation("s002", 10.0, face=0.60, body=0.60, base_score=0.99)

    selected = select_observations([generic, dual], max_segments=1, min_base_score=0.35)

    assert selected == [dual]


def test_selection_fails_when_mandatory_coverage_pair_violates_overlap_constraints() -> None:
    face = _observation("s001", 0.0, face=0.95, body=0.40, base_score=0.90)
    body = _observation("s001", 1.0, face=0.40, body=0.95, base_score=0.89)

    with pytest.raises(ObservationError, match="incompatible with overlap/source constraints"):
        select_observations(
            [face, body],
            max_segments=2,
            min_base_score=0.35,
            max_per_source=2,
        )


def test_selection_fails_when_separate_mandatory_windows_do_not_fit_segment_budget() -> None:
    face = _observation("s001", 0.0, face=0.95, body=0.40, base_score=0.90)
    body = _observation("s002", 10.0, face=0.40, body=0.95, base_score=0.89)

    with pytest.raises(ObservationError, match="cannot fit within max_segments"):
        select_observations(
            [face, body],
            max_segments=1,
            min_base_score=0.35,
        )


def test_existing_view_and_source_diversity_still_fills_remaining_budget() -> None:
    face = _observation("s001", 0.0, face=0.95, body=0.50, base_score=0.80, view="front")
    body = _observation("s002", 10.0, face=0.50, body=0.95, base_score=0.79, view="left_profile")
    rear = _observation("s003", 20.0, face=0.30, body=0.80, base_score=0.77, view="rear")
    duplicate_view = _observation("s004", 30.0, face=0.30, body=0.80, base_score=0.76, view="front")

    selected = select_observations(
        [face, body, rear, duplicate_view],
        max_segments=3,
        min_base_score=0.35,
        max_per_source=2,
    )

    assert len(selected) == 3
    assert {item.view for item in selected} == {"front", "left_profile", "rear"}
