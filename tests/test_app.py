from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.package import build_package
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
        "gesture_amplitude": 0.83,
        "head_motion": 0.61,
    },
    "expression": {
        "gaze_strength": 0.77,
        "speech_motion": 0.66,
    },
    "runtime": {"gesture_intensity": 0.8},
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


def test_import_activate_cue_and_motor_state(tmp_path: Path, monkeypatch):
    library = tmp_path / "library"
    monkeypatch.setattr(app_module, "body_library", lambda: library)
    monkeypatch.setattr(app_module, "runtime", BodyRuntime())
    client = TestClient(app_module.app)

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
    assert payload["body_id"] == "api-person"
    assert payload["gesture"]["id"] == "small_shrug"
    assert 0.0 < payload["gesture"]["amplitude"] <= 1.0
    assert payload["gaze"]["strength"] == BODYPRINT["expression"]["gaze_strength"]


def test_motor_state_requires_activated_bodyprint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(app_module, "body_library", lambda: tmp_path / "library")
    monkeypatch.setattr(app_module, "runtime", BodyRuntime())
    client = TestClient(app_module.app)
    response = client.get("/api/v1/runtime/motor-state")
    assert response.status_code == 409
