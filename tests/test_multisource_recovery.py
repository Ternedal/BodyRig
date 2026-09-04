from __future__ import annotations

import pytest

from bodyrig.recover_cli import _aggregate_bodyprints, _proof_track_id, _select_tracks
from bodyrig.recovery import RecoveredTrack, RecoveryFrame, RecoveryResult


def joints(shift: float = 0.0):
    return {
        "head": (0.0 + shift, 1.8, 0.0),
        "left_shoulder": (-0.22 + shift, 1.45, 0.0),
        "right_shoulder": (0.22 + shift, 1.45, 0.0),
        "left_hip": (-0.16 + shift, 1.0, 0.0),
        "right_hip": (0.16 + shift, 1.0, 0.0),
        "left_wrist": (-0.55 + shift, 1.15, 0.0),
        "right_wrist": (0.55 + shift, 1.15, 0.0),
        "left_ankle": (-0.12 + shift, 0.0, 0.0),
        "right_ankle": (0.12 + shift, 0.0, 0.0),
    }


def track(name: str, *, count: int, confidence: float = 0.9, shift: float = 0.0):
    frames = tuple(
        RecoveryFrame(
            timestamp_ms=index * 100,
            joints=joints(shift),
            confidence=confidence,
        )
        for index in range(count)
    )
    return RecoveredTrack(track_id=name, frames=frames)


def result(*tracks: RecoveredTrack):
    return RecoveryResult(tracks=tracks, adapter="fixture", revision="v1")


def test_selects_strongest_observed_track_independently_per_source():
    selected = _select_tracks(
        result(
            track("s00-t1", count=10, confidence=0.7),
            track("s00-t2", count=4, confidence=1.0),
            track("s01-t4", count=5, confidence=0.6),
            track("s01-t3", count=5, confidence=0.9),
            track("s02-t9", count=6, confidence=0.8),
        ),
        None,
        source_count=3,
    )
    assert [item.track_id for item in selected] == ["s00-t1", "s01-t3", "s02-t9"]


def test_explicit_track_remains_diagnostic_single_track_override():
    selected = _select_tracks(
        result(track("s00-t1", count=5), track("s01-t2", count=5)),
        "s01-t2",
        source_count=2,
    )
    assert [item.track_id for item in selected] == ["s01-t2"]


def test_multi_segment_bodyprint_never_computes_motion_across_clip_boundaries():
    # Each track is perfectly static internally, but the second clip is translated
    # by 100 coordinate units. Concatenating the tracks before extracting motion
    # would create an enormous fake velocity at the clip boundary.
    first = track("s00-t1", count=12, shift=0.0)
    second = track("s01-t1", count=12, shift=100.0)

    bodyprint = _aggregate_bodyprints((first, second))

    assert bodyprint["motion"]["energy"] == pytest.approx(0.0)
    assert bodyprint["motion"]["head_motion"] == pytest.approx(0.0)
    assert 0.20 < bodyprint["shape"]["shoulder_to_height"] < 0.30


def test_aggregate_track_id_is_deterministic_and_bounded():
    tracks = (track("s00-t1", count=2), track("s01-t7", count=2))
    value = _proof_track_id(tracks)
    assert value.startswith("aggregate-")
    assert len(value) < 160
    assert value == _proof_track_id(tracks)


def test_multi_source_recovery_requires_evidence_from_three_sources_when_available():
    with pytest.raises(ValueError, match="too few source segments"):
        _select_tracks(
            result(track("s00-t1", count=5), track("s01-t1", count=5)),
            None,
            source_count=10,
        )
