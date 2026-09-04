from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.bridges.opencv_identity_capture import (
    _candidate_score,
    _coverage_profile,
    _framing_score,
    _lighting_score,
    _read_request,
    _sharpness_score,
)


def test_identity_framing_rewards_centered_full_body_and_penalizes_clipping():
    centered = _framing_score((220, 60, 260, 760), 720, 900)
    clipped = _framing_score((0, 0, 710, 898), 720, 900)
    tiny = _framing_score((320, 300, 70, 120), 720, 900)
    assert centered > clipped
    assert centered > tiny
    assert 0 <= clipped <= 1


def test_identity_candidate_score_rewards_face_and_quality():
    plain = _candidate_score(framing=0.8, face=False, sharpness=0.7, lighting=0.7, detector=0.8)
    face = _candidate_score(framing=0.8, face=True, sharpness=0.7, lighting=0.7, detector=0.8)
    sharper = _candidate_score(framing=0.8, face=True, sharpness=0.95, lighting=0.8, detector=0.9)
    assert plain < face < sharper <= 1.0


def test_identity_quality_helpers_are_bounded_and_monotonic():
    assert _sharpness_score(0.0) == 0.0
    assert _sharpness_score(40.0) < _sharpness_score(400.0) <= 1.0
    good_light = _lighting_score(128.0, 45.0)
    dark = _lighting_score(3.0, 2.0)
    blown = _lighting_score(252.0, 2.0)
    assert good_light > dark
    assert good_light > blown
    assert 0 <= good_light <= 1


def test_identity_coverage_is_observation_derived_and_back_stays_unknown_zero():
    coverage = _coverage_profile(observed=20, face_frames=6, full_body_frames=5, side_frames=2)
    assert 0 < coverage["face"] <= 1
    assert 0 < coverage["full_body"] <= 1
    assert coverage["clothing"] == coverage["full_body"]
    assert coverage["back"] == 0.0
    assert 0 < coverage["side"] <= 1


def test_identity_request_requires_exact_adapter_revision_and_fields(tmp_path: Path):
    request = {
        "format": "bodyrig-identity-capture-request",
        "version": 1,
        "adapter": "opencv-identity-rgba",
        "revision": "1",
        "source_count": 2,
        "subject_track_id": "track-7",
        "observed_frames": 100,
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")

    loaded = _read_request(path, "opencv-identity-rgba", "1")
    assert loaded["subject_track_id"] == "track-7"

    with pytest.raises(RuntimeError, match="adapter/revision mismatch"):
        _read_request(path, "other-adapter", "1")

    request["source_path"] = "must-not-be-accepted.mp4"
    path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(RuntimeError, match="fields do not match"):
        _read_request(path, "opencv-identity-rgba", "1")
