import pytest

from bodyrig.recover_cli import _select_track
from bodyrig.recovery import RecoveredTrack, RecoveryFrame, RecoveryResult


def track(name, count=2):
    frames = tuple(RecoveryFrame(timestamp_ms=i * 40, joints={"head": (0.0, 1.0, 0.0)}) for i in range(count))
    return RecoveredTrack(track_id=name, frames=frames)


def result(*tracks):
    return RecoveryResult(tracks=tracks, adapter="fixture", revision="v1")


def test_single_track_auto_selects():
    assert _select_track(result(track("s00-t1")), None).track_id == "s00-t1"


def test_multiple_tracks_require_explicit_selection():
    with pytest.raises(ValueError, match="multiple"):
        _select_track(result(track("s00-t1"), track("s00-t2")), None)


def test_explicit_track_selection():
    selected = _select_track(result(track("s00-t1"), track("s00-t2")), "s00-t2")
    assert selected.track_id == "s00-t2"


def test_unknown_track_reports_candidates():
    with pytest.raises(ValueError, match="available"):
        _select_track(result(track("s00-t1")), "missing")
