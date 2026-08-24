from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bodyrig.app as app_module
import bodyrig.ui_jobs as ui_jobs_module
from bodyrig.person_profiles import create_profile


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    return TestClient(app_module.app)


def _ready_person(tmp_path: Path, monkeypatch) -> dict:
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
    return profile


@pytest.mark.parametrize(
    "payload",
    [
        {"feedback": "Armene skal være kortere"},
        {"feedback": "Armene skal være kortere", "changes": []},
    ],
)
def test_body_build_api_requires_explicit_reviewed_changes(tmp_path: Path, monkeypatch, payload: dict) -> None:
    profile = _ready_person(tmp_path, monkeypatch)
    response = _client(monkeypatch).post(
        f"/api/v1/people/{profile['person_id']}/body/build",
        json=payload,
    )
    assert response.status_code == 409
    assert "exact reviewed proposal changes" in response.json()["detail"]


def test_ui_job_manager_rejects_feedback_without_reviewed_changes(tmp_path: Path, monkeypatch) -> None:
    profile = _ready_person(tmp_path, monkeypatch)
    with pytest.raises(ui_jobs_module.UiJobError, match="exact reviewed proposal changes"):
        ui_jobs_module.manager.start_body_build(
            profile["person_id"],
            feedback="Armene skal være kortere",
            changes=None,
        )
