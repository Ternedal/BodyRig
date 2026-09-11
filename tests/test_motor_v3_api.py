from __future__ import annotations

from fastapi.testclient import TestClient

import bodyrig.app as app_module
from bodyrig.runtime import BodyRuntime


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {
        "energy": 0.72,
        "gesture_frequency": 0.81,
        "gesture_amplitude": 0.63,
        "head_motion": 0.58,
        "turn_speed": 0.44,
        "walk_cadence_spm": 116.0,
        "movement_observed_frames": 60,
        "movement_observed_seconds": 4.5,
        "gait_step_events": 7,
        "idle_observed_seconds": 0.9,
        "posture_torso_lean_degrees": 5.2,
        "posture_torso_forward_lean_degrees": 4.8,
        "posture_torso_right_lean_degrees": -1.2,
        "posture_shoulder_tilt_degrees": 1.3,
        "posture_shoulder_roll_degrees": -1.3,
        "posture_hip_tilt_degrees": 0.8,
        "posture_hip_roll_degrees": -0.8,
        "posture_head_offset_to_height": 0.041,
        "posture_head_forward_offset_to_height": 0.036,
        "posture_head_right_offset_to_height": 0.019,
        "stride_length_to_height": 0.34,
        "stance_width_to_height": 0.13,
        "vertical_bounce_to_height": 0.024,
        "left_arm_swing_to_height": 0.20,
        "right_arm_swing_to_height": 0.18,
        "arm_swing_to_height": 0.19,
        "arm_swing_asymmetry": 0.10,
        "turn_speed_degrees_per_second": 79.2,
        "transition_intensity": 0.31,
        "idle_sway_to_height": 0.012,
    },
}


def _client(monkeypatch) -> tuple[TestClient, BodyRuntime]:
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    runtime = BodyRuntime()
    runtime.activate("person-a", BODYPRINT)
    monkeypatch.setattr(app_module, "runtime", runtime)
    return TestClient(app_module.app), runtime


def test_v2_cue_and_v3_motor_state_share_the_canonical_app_runtime(monkeypatch) -> None:
    client, runtime = _client(monkeypatch)

    response = client.post(
        "/api/v2/runtime/cue",
        json={
            "type": "modelrig-body-cue",
            "version": 2,
            "utterance_id": "u-walk",
            "locomotion": {"action": "walk"},
        },
    )
    assert response.status_code == 200
    assert response.json()["cue"]["version"] == 2
    assert response.json()["cue"]["locomotion"] == {"action": "walk"}
    assert runtime.snapshot().cue == response.json()["cue"]

    motor = client.get("/api/v3/runtime/motor-state")
    assert motor.status_code == 200
    state = motor.json()
    assert state["version"] == 3
    assert state["locomotion"]["action"] == "walk"
    assert state["locomotion"]["cadence_spm"] == 116.0
    assert state["locomotion"]["stride_length_to_height"] == 0.34
    assert state["locomotion"]["left_arm_swing_to_height"] == 0.20
    assert state["locomotion"]["right_arm_swing_to_height"] == 0.18
    assert state["locomotion"]["left_arm_swing_to_height"] > state["locomotion"]["right_arm_swing_to_height"]


def test_v2_natural_posture_is_realized_only_through_v3_motor_endpoint(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    cue = client.post(
        "/api/v2/runtime/cue",
        json={
            "type": "modelrig-body-cue",
            "version": 2,
            "utterance_id": "u-natural-posture",
            "posture": "natural",
        },
    )
    assert cue.status_code == 200

    assert client.get("/api/v1/runtime/motor-state").status_code == 409
    assert client.get("/api/v2/runtime/motor-state").status_code == 409

    response = client.get("/api/v3/runtime/motor-state")
    assert response.status_code == 200
    posture = response.json()["posture"]
    assert posture["id"] == "natural"
    assert posture["torso_forward_lean_degrees"] == 4.8
    assert posture["torso_right_lean_degrees"] == -1.2
    assert posture["shoulder_roll_degrees"] == -1.3
    assert posture["head_right_offset_to_height"] == 0.019
    assert "locomotion" not in response.json()


def test_v1_cue_endpoint_remains_v1_only(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    response = client.post(
        "/api/v1/runtime/cue",
        json={
            "type": "modelrig-body-cue",
            "version": 2,
            "utterance_id": "u-walk",
            "locomotion": {"action": "walk"},
        },
    )
    assert response.status_code == 422


def test_v2_cue_cannot_be_read_through_old_motor_endpoints(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    response = client.post(
        "/api/v2/runtime/cue",
        json={
            "type": "modelrig-body-cue",
            "version": 2,
            "utterance_id": "u-turn",
            "locomotion": {"action": "turn_right"},
        },
    )
    assert response.status_code == 200

    old_v1 = client.get("/api/v1/runtime/motor-state")
    old_v2 = client.get("/api/v2/runtime/motor-state")
    assert old_v1.status_code == 409
    assert old_v2.status_code == 409
    assert "requires Motor State v3" in old_v1.json()["detail"]
    assert "requires Motor State v3" in old_v2.json()["detail"]

    current = client.get("/api/v3/runtime/motor-state")
    assert current.status_code == 200
    assert current.json()["locomotion"]["action"] == "turn_right"


def test_v3_motor_endpoint_fails_closed_without_a_cue(monkeypatch) -> None:
    client, runtime = _client(monkeypatch)
    runtime.activate("person-a", BODYPRINT)
    response = client.get("/api/v3/runtime/motor-state")
    assert response.status_code == 409
    assert "no active BodyCue" in response.json()["detail"]
