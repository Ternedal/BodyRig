import pytest

from bodyrig.bridges.phalp import PhalpConversionError, canonicalize_phalp_results


def joints(offset=0.0):
    result = [[0.0, 0.0, 0.0] for _ in range(25)]
    result[0] = [0.0 + offset, 1.8, 0.0]   # head ref / nose
    result[2] = [0.22 + offset, 1.45, 0.0] # R shoulder
    result[4] = [0.55 + offset, 1.15, 0.0] # R wrist
    result[5] = [-0.22 + offset, 1.45, 0.0]
    result[7] = [-0.55 + offset, 1.15, 0.0]
    result[9] = [0.16 + offset, 1.0, 0.0]
    result[11] = [0.12 + offset, 0.0, 0.0]
    result[12] = [-0.16 + offset, 1.0, 0.0]
    result[14] = [-0.12 + offset, 0.0, 0.0]
    return result


def frame(time, *, age=0, offset=0.0, tid=7, conf=0.9):
    return {
        "time": time,
        "tid": [tid],
        "tracked_time": [age],
        "3d_joints": [joints(offset)],
        "conf": [conf],
    }


def test_converts_openpose_subset_and_timestamps():
    tracks = canonicalize_phalp_results({"a": frame(0), "b": frame(25, offset=0.1)}, fps=25.0, source_index=2)
    assert len(tracks) == 1
    assert tracks[0]["track_id"] == "s02-t7"
    assert tracks[0]["frames"][1]["timestamp_ms"] == 1000
    assert tracks[0]["frames"][0]["joints"]["left_shoulder"] == [-0.22, 1.45, 0.0]
    assert tracks[0]["frames"][0]["joints"]["right_wrist"] == [0.55, 1.15, 0.0]


def test_predicted_occlusion_states_are_not_observations():
    tracks = canonicalize_phalp_results({"a": frame(0), "b": frame(1, age=1), "c": frame(2, offset=0.1)}, fps=25.0, source_index=0)
    assert len(tracks[0]["frames"]) == 2
    assert [item["timestamp_ms"] for item in tracks[0]["frames"]] == [0, 80]


def test_low_confidence_observations_are_removed():
    tracks = canonicalize_phalp_results({"a": frame(0, conf=0.1), "b": frame(1), "c": frame(2)}, fps=25.0, source_index=0)
    assert len(tracks[0]["frames"]) == 2


def test_invalid_fps_fails_closed():
    with pytest.raises(PhalpConversionError, match="fps"):
        canonicalize_phalp_results({}, fps=0.0, source_index=0)


def test_misaligned_frame_arrays_fail_closed():
    bad = frame(0)
    bad["tracked_time"] = []
    with pytest.raises(PhalpConversionError, match="misaligned"):
        canonicalize_phalp_results({"a": bad}, fps=25.0, source_index=0)
