from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.guided_app as guided_app
from bodyrig.person_profiles import create_profile, load_profile


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path, str]:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(guided_app, "person_library", lambda: root)
    return TestClient(guided_app.app), root, profile["person_id"]


def _payload() -> dict:
    return {
        "default_language": "da",
        "communication": {
            "directness": 0.8,
            "warmth": 0.7,
            "playfulness": 0.65,
            "formality": 0.25,
            "verbosity": 0.35,
            "initiative": 0.75,
        },
        "authored_notes": "Tør og underspillet. Ikke serviceagtig.",
        "style_exemplars": ["Ja ja, det går nok."],
        "body_revision": None,
    }


def test_guided_preview_is_non_mutating_and_returns_audition_suite(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    value = response.json()
    assert len(value["blueprint_sha256"]) == 64
    assert value["blueprint"]["communication"]["directness"] == 0.8
    assert value["blueprint"]["grounding"] == {
        "communication": "operator-authored",
        "embodiment": "operator-authored",
        "body_revision": None,
    }
    assert "blueprint_sha256=" in value["candidate"]["style_notes"]
    assert len(value["audition_suite"]["probes"]) == 6
    assert load_profile(root, person_id)["personality_revisions"] == []
    assert not (root / "personality-blueprints").exists()


def test_guided_save_creates_evidence_then_candidate_without_activation(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    payload = {**_payload(), "feedback": "guided v1"}

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/revisions",
        json=payload,
    )

    assert response.status_code == 200
    value = response.json()
    assert value["saved_personality_revision"] == "personality-r0001"
    profile = value["profile"]
    assert profile["active_person_revision"] is None
    assert profile["personality_revisions"][0]["feedback"] == "guided v1"
    digest = value["blueprint_sha256"]
    evidence = root / "personality-blueprints" / person_id / f"{digest}.json"
    assert evidence.is_file()
    assert f"blueprint_sha256={digest}" in profile["personality_revisions"][0]["style_notes"]


def test_guided_api_rejects_out_of_range_traits_before_authoring(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    payload = _payload()
    payload["communication"]["warmth"] = 1.5

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/revisions",
        json={**payload, "feedback": "bad"},
    )

    assert response.status_code == 422
    assert load_profile(root, person_id)["personality_revisions"] == []
    assert not (root / "personality-blueprints").exists()


def test_guided_api_refuses_unknown_body_grounding(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    payload = _payload()
    payload["body_revision"] = "body-r0001"

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/preview",
        json=payload,
    )

    assert response.status_code == 422
    assert "not registered" in response.json()["detail"]
    assert load_profile(root, person_id)["personality_revisions"] == []
