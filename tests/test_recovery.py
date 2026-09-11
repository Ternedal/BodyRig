import math

import pytest

from bodyrig.movement_identity import require_movement_identity
from bodyrig.recovery import BodyprintExtractor, RecoveryError, parse_recovery_result


def frame(ts, shift=0.0):
    return {"timestamp_ms":ts,"confidence":0.9,"joints":{"head":[0.0+shift,1.8,0.0],"left_shoulder":[-0.22+shift,1.45,0.0],"right_shoulder":[0.22+shift,1.45,0.0],"left_hip":[-0.16+shift,1.0,0.0],"right_hip":[0.16+shift,1.0,0.0],"left_wrist":[-0.55-shift,1.15,0.0],"right_wrist":[0.55+shift,1.15,0.0],"left_ankle":[-0.12+shift,0.0,0.0],"right_ankle":[0.12+shift,0.0,0.0]}}


def movement_frame(index: int) -> dict:
    ts = index * 100
    idle = index <= 5
    phase = 1.0 if ((index - 6) // 5) % 2 == 0 else -1.0
    if idle:
        phase = 0.0
    bounce = 0.0 if idle else 0.018 * math.sin(index * math.pi / 2.5)
    left_forward = 0.0 if idle else 0.18 * phase
    right_forward = -left_forward
    arm = 0.0 if idle else -0.16 * phase
    return {
        "timestamp_ms": ts,
        "confidence": 0.95,
        "joints": {
            "head": [0.02, 1.80 + bounce, 0.075],
            "neck": [0.0, 1.56 + bounce, 0.045],
            "left_shoulder": [-0.22, 1.45 + bounce, 0.05],
            "right_shoulder": [0.22, 1.44 + bounce, 0.05],
            "left_elbow": [-0.38, 1.30 + bounce, arm * 0.55],
            "right_elbow": [0.38, 1.30 + bounce, -arm * 0.55],
            "left_wrist": [-0.52, 1.12 + bounce, arm],
            "right_wrist": [0.52, 1.12 + bounce, -arm],
            "mid_hip": [0.0, 1.0 + bounce, 0.0],
            "left_hip": [-0.16, 1.005 + bounce, 0.0],
            "right_hip": [0.16, 0.995 + bounce, 0.0],
            "left_knee": [-0.13, 0.52 + bounce, left_forward * 0.45],
            "right_knee": [0.13, 0.52 + bounce, right_forward * 0.45],
            "left_ankle": [-0.12, 0.0 + bounce, left_forward],
            "right_ankle": [0.12, 0.0 + bounce, right_forward],
        },
    }


def payload(frames): return {"format":"bodyrig-recovery","version":1,"adapter":"fixture","revision":"fixture-v1","tracks":[{"track_id":"person-1","frames":frames}]}


def test_parse_and_extract_observed_bodyprint():
    result=parse_recovery_result(payload([frame(0),frame(100,0.08),frame(200,0.16)])); bodyprint=BodyprintExtractor().extract(result.tracks[0])
    assert 0.20 < bodyprint["shape"]["shoulder_to_height"] < 0.30
    assert 0.0 <= bodyprint["motion"]["energy"] <= 1.0
    assert "height_scale" not in bodyprint["shape"]


def test_extracts_complete_source_derived_movement_identity():
    result = parse_recovery_result(payload([movement_frame(index) for index in range(30)]))
    bodyprint = BodyprintExtractor().extract(result.tracks[0])
    movement = require_movement_identity(bodyprint)
    motion = bodyprint["motion"]
    assert movement["complete"] is True
    assert motion["movement_observed_frames"] == 30
    assert motion["movement_observed_seconds"] >= 2.8
    assert motion["idle_observed_seconds"] >= 0.5
    assert motion["gait_step_events"] >= 2
    assert 30.0 <= motion["walk_cadence_spm"] <= 240.0
    assert motion["stride_length_to_height"] > 0.0
    assert motion["stance_width_to_height"] > 0.0
    assert "posture_torso_lean_degrees" in motion
    assert "posture_torso_forward_lean_degrees" in motion
    assert "posture_torso_right_lean_degrees" in motion
    assert "posture_shoulder_roll_degrees" in motion
    assert "posture_hip_roll_degrees" in motion
    assert "posture_head_forward_offset_to_height" in motion
    assert "posture_head_right_offset_to_height" in motion
    assert "turn_speed_degrees_per_second" in motion
    assert "idle_sway_to_height" in motion


def test_signed_posture_uses_body_relative_forward_and_right_axes():
    result = parse_recovery_result(payload([movement_frame(index) for index in range(30)]))
    motion = BodyprintExtractor().extract(result.tracks[0])["motion"]

    # The synthetic shoulders define +X as anatomical right, so BodyRig's
    # established shoulder-relative forward basis is +Z. These signs therefore
    # prove the extractor is not reporting camera/world-axis magnitudes.
    assert motion["posture_torso_forward_lean_degrees"] > 0.0
    assert abs(motion["posture_torso_right_lean_degrees"]) < 0.2
    assert motion["posture_shoulder_roll_degrees"] < 0.0
    assert motion["posture_hip_roll_degrees"] < 0.0
    assert motion["posture_head_forward_offset_to_height"] > 0.0
    assert motion["posture_head_right_offset_to_height"] > 0.0


def test_unobserved_timestamp_gaps_do_not_count_as_movement_or_idle_coverage():
    sparse = [frame(index * 1000) for index in range(24)]
    result = parse_recovery_result(payload(sparse))
    bodyprint = BodyprintExtractor().extract(result.tracks[0])
    motion = bodyprint["motion"]
    assert "movement_observed_frames" not in motion
    assert "movement_observed_seconds" not in motion
    assert motion["idle_observed_seconds"] == 0.0
    assert "idle_sway_to_height" not in motion


def test_nonwalking_track_does_not_gain_gait_authority():
    frames = [movement_frame(index) for index in range(6)] + [movement_frame(5) | {"timestamp_ms": 600 + index * 100} for index in range(24)]
    result = parse_recovery_result(payload(frames))
    bodyprint = BodyprintExtractor().extract(result.tracks[0])
    assert bodyprint["motion"]["gait_step_events"] == 0
    assert "walk_cadence_spm" not in bodyprint["motion"]


def test_non_finite_joint_rejected():
    bad=payload([frame(0),frame(100)]); bad["tracks"][0]["frames"][1]["joints"]["head"][0]=float("nan")
    with pytest.raises(RecoveryError,match="finite"): parse_recovery_result(bad)


def test_out_of_order_time_rejected():
    with pytest.raises(RecoveryError,match="strictly increasing"): parse_recovery_result(payload([frame(100),frame(100)]))


def test_adapter_identity_pinned():
    with pytest.raises(RecoveryError,match="identity mismatch"): parse_recovery_result(payload([frame(0),frame(100)]),expected_adapter="hmr2")