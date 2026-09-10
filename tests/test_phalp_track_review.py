from __future__ import annotations

import pytest

from bodyrig.bridges.phalp_track_review import (
    PhalpTrackReviewError,
    canonicalize_phalp_track_review,
)


def _frame(time: int, *, tids=(1, 2), ages=(0, 0), confs=(0.9, 0.8), bboxes=None):
    if bboxes is None:
        bboxes = ([10.0, 20.0, 100.0, 200.0], [300.0, 40.0, 120.0, 220.0])
    return {
        "time": time,
        "tid": list(tids),
        "tracked_time": list(ages),
        "conf": list(confs),
        "bbox": [list(item) for item in bboxes],
    }


def test_track_review_exports_observed_source_local_tracks_without_target_choice():
    result = canonicalize_phalp_track_review(
        {"a": _frame(0), "b": _frame(25)},
        fps=25.0,
        source_index=3,
    )
    assert result["format"] == "bodyrig-phalp-track-review"
    assert result["version"] == 1
    assert result["source_index"] == 3
    assert result["target_track_id"] is None
    assert result["human_identity_attestation_required"] is True
    assert result["biometric_identity_inference_used"] is False
    assert result["generic_guessing_permitted"] is False
    assert result["reconstruction_permitted"] is False
    assert result["production_activation"] is False
    assert [item["track_id"] for item in result["tracks"]] == ["s03-t1", "s03-t2"]
    assert result["tracks"][0]["samples"][1]["timestamp_ms"] == 1000
    assert result["tracks"][0]["samples"][0]["bbox_tlwh"] == [10.0, 20.0, 100.0, 200.0]


def test_track_review_discards_predicted_states_and_low_confidence_observations():
    result = canonicalize_phalp_track_review(
        {
            "a": _frame(0, ages=(0, 0), confs=(0.9, 0.1)),
            "b": _frame(25, ages=(1, 0), confs=(0.9, 0.1)),
            "c": _frame(50, ages=(0, 0), confs=(0.9, 0.1)),
        },
        fps=25.0,
        source_index=0,
    )
    assert [item["track_id"] for item in result["tracks"]] == ["s00-t1"]
    assert result["tracks"][0]["observation_count"] == 2
    assert [sample["timestamp_ms"] for sample in result["tracks"][0]["samples"]] == [0, 2000]


def test_track_review_samples_long_tracks_deterministically_and_bounded():
    frames = {str(i): _frame(i, tids=(7,), ages=(0,), confs=(0.9,), bboxes=([1, 2, 30, 40],)) for i in range(20)}
    result = canonicalize_phalp_track_review(
        frames,
        fps=10.0,
        source_index=1,
        max_samples_per_track=6,
    )
    track = result["tracks"][0]
    assert track["observation_count"] == 20
    assert len(track["samples"]) == 6
    assert track["samples"][0]["timestamp_ms"] == 0
    assert track["samples"][-1]["timestamp_ms"] == 1900


def test_track_review_fails_closed_on_misaligned_arrays_and_invalid_boxes():
    broken = _frame(0)
    broken["bbox"] = broken["bbox"][:1]
    with pytest.raises(PhalpTrackReviewError, match="misaligned"):
        canonicalize_phalp_track_review({"a": broken}, fps=25.0, source_index=0)

    bad_box = _frame(0, tids=(1,), ages=(0,), confs=(0.9,), bboxes=([0, 0, -1, 10],))
    with pytest.raises(PhalpTrackReviewError, match="positive"):
        canonicalize_phalp_track_review({"a": bad_box}, fps=25.0, source_index=0)


def test_track_review_requires_valid_fps_and_bounds():
    with pytest.raises(PhalpTrackReviewError, match="fps"):
        canonicalize_phalp_track_review({}, fps=0.0, source_index=0)
    with pytest.raises(PhalpTrackReviewError, match="source_index"):
        canonicalize_phalp_track_review({}, fps=25.0, source_index=-1)
    with pytest.raises(PhalpTrackReviewError, match="max_samples"):
        canonicalize_phalp_track_review({}, fps=25.0, source_index=0, max_samples_per_track=99)
