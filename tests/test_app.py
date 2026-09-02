from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
import bodyrig.ui_jobs as ui_jobs_module
from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.package import build_package
from bodyrig.person_profiles import create_profile
from bodyrig.runtime import BodyRuntime


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {
        "energy": 0.72,
        "gesture_frequency": 0.57,
        "gesture_amplitude": 0.83,
        "head_motion": 0.61,
        "turn_speed": 0.42,
        "walk_cadence_spm": 112.0,
    },
    "expression": {
        "blink_rate_per_min": 17.0,
        "gaze_strength": 0.77,
        "head_tilt": 0.31,
        "speech_motion": 0.66,
    },
    "runtime": {
        "idle_strength": 0.41,
        "gaze_smoothing": 0.52,
        "gesture_intensity": 0.8,
        "breathing_strength": 0.28,
    },
}


def _package(path: Path) -> Path:
    fitted = ProceduralAvatarFitter().fit(BODYPRINT, name="API Person")
    provenance = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-08-23T10:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [
            {"stage": "body-recovery", "adapter": "fixture", "revision": "fixture-v1"},
            {"stage": "avatar-fitting", "adapter": fitted.adapter, "revision": fitted.revision},
        ],
    }
    return build_package(
        path,
        body_id="api-person",
        name="API Person",
        avatar_vrm=fitted.avatar_vrm,
        bodyprint=BODYPRINT,
        provenance=provenance,
        thumbnail_png=fitted.thumbnail_png,
    )


def _client(monkeypatch) -> TestClient:
    # Starlette TestClient uses the synthetic peer name "testclient", which the
    # production request guard intentionally rejects because it is not a loopback IP.
    # Tests opt in explicitly instead of weakening the runtime boundary.
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    return TestClient(app_module.app)


def test_import_activate_cue_and_motor_state(tmp_path: Path, monkeypatch):
    library = tmp_path / "library"
    monkeypatch.setattr(app_module, "body_library", lambda: library)
    monkeypatch.setattr(app_module, "runtime", BodyRuntime())
    client = _client(monkeypatch)

    package = _package(tmp_path / "api-person.mrbody")
    imported = client.post("/api/v1/bodies/import", json={"path": str(package)})
    assert imported.status_code == 200
    assert imported.json()["id"] == "api-person"

    activated = client.post("/api/v1/bodies/api-person/activate")
    assert activated.status_code == 200
    assert activated.json()["active_body_id"] == "api-person"

    cue = client.post(
        "/api/v1/runtime/cue",
        json={
            "type": "modelrig-body-cue",
            "version": 1,
            "utterance_id": "u-api",
            "body_id": "api-person",
            "emotion": "amused",
            "intensity": 0.6,
            "energy": 0.5,
            "gesture": "small_shrug",
            "gaze": "user",
        },
    )
    assert cue.status_code == 200

    motor = client.get("/api/v1/runtime/motor-state")
    assert motor.status_code == 200
    payload = motor.json()
    assert payload["type"] == "bodyrig-motor-state"
    assert payload["version"] == 1
    assert payload["body_id"] == "api-person"
    assert payload["gesture"]["id"] == "small_shrug"
    assert 0.0 < payload["gesture"]["amplitude"] <= 1.0
    assert payload["gaze"]["strength"] == BODYPRINT["expression"]["gaze_strength"]

    motor_v2 = client.get("/api/v2/runtime/motor-state")
    assert motor_v2.status_code == 200
    payload_v2 = motor_v2.json()
    expected_performed = dict(payload)
    expected_performed["version"] = 2
    expected_performed["embodiment"] = payload_v2["embodiment"]
    assert payload_v2 == expected_performed
    assert payload_v2["embodiment"] == {
        "source": "modelrig-bodyprint-v1",
        "observed": {
            "energy": 0.72,
            "gesture_frequency": 0.57,
            "gesture_amplitude": 0.83,
            "head_motion": 0.61,
            "turn_speed": 0.42,
            "walk_cadence_spm": 112.0,
            "blink_rate_per_min": 17.0,
            "gaze_strength": 0.77,
            "head_tilt": 0.31,
            "speech_motion": 0.66,
            "idle_strength": 0.41,
            "gaze_smoothing": 0.52,
            "gesture_intensity": 0.8,
            "breathing_strength": 0.28,
        },
    }


def test_motor_state_requires_activated_bodyprint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(app_module, "body_library", lambda: tmp_path / "library")
    monkeypatch.setattr(app_module, "runtime", BodyRuntime())
    client = _client(monkeypatch)
    assert client.get("/api/v1/runtime/motor-state").status_code == 409
    assert client.get("/api/v2/runtime/motor-state").status_code == 409


def test_body_build_api_rejects_changes_not_generated_from_same_feedback(tmp_path: Path, monkeypatch):
    people = tmp_path / "people"
    profile = create_profile(
        people,
        display_name="Reviewed Body",
        stash_performer={"id": "stash-1", "name": "Reviewed Body", "disambiguation": ""},
    )
    monkeypatch.setattr(ui_jobs_module, "person_library", lambda: people)
    monkeypatch.setattr(
        ui_jobs_module,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": "a" * 40, "root": str(tmp_path)},
    )
    monkeypatch.setenv("STASH_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("STASH_API_KEY", "test-only-token")
    client = _client(monkeypatch)

    response = client.post(
        f"/api/v1/people/{profile['person_id']}/body/build",
        json={
            "feedback": "Armene skal være kortere",
            "changes": [
                {
                    "field": "shape.shoulder_to_height",
                    "delta": 0.010,
                    "reason": "shoulders should be broader",
                }
            ],
        },
    )
    assert response.status_code == 409
    assert "exact subset" in response.json()["detail"]
