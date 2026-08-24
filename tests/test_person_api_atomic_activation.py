from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
from bodyrig.person_profiles import add_body_revision, load_profile


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    people = tmp_path / "people"
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(app_module, "person_library", lambda: people)
    return TestClient(app_module.app)


def _create_components(client: TestClient, root: Path, person_id: str) -> None:
    add_body_revision(
        root,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256="a" * 64,
        package_path=r"C:\BodyRig\anna.mrbody",
        feedback="body candidate",
    )
    voice = client.post(
        f"/api/v1/people/{person_id}/voice/revisions",
        json={"voice_id": "anna-voice-0001", "package_path": None, "feedback": "voice candidate"},
    )
    assert voice.status_code == 200
    personality = client.post(
        f"/api/v1/people/{person_id}/personality/revisions",
        json={
            "instructions": "Du er Anna. Rolig, præcis og med tør humor.",
            "default_language": "da",
            "style_notes": "rolig og tør",
            "feedback": "personality candidate",
        },
    )
    assert personality.status_code == 200


def test_components_remain_candidates_until_person_revision_is_approved(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None})
    assert created.status_code == 200
    person_id = created.json()["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)

    profile = load_profile(root, person_id)
    assert profile["active_person_revision"] is None

    old_path = client.post(f"/api/v1/people/{person_id}/activate/body/body-r0001")
    assert old_path.status_code == 409
    assert "cannot be activated independently" in old_path.json()["detail"]

    bad = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json={
            "body_revision": "body-r0001",
            "voice_revision": "voice-r0001",
            "personality_revision": "personality-r0001",
            "body_voice_match": True,
            "voice_personality_match": False,
            "body_personality_match": True,
            "overall_coherent": True,
            "compatibility_note": "Stemmen føles ikke som samme person.",
            "feedback": "reject",
            "activate": True,
        },
    )
    assert bad.status_code == 422
    assert "voice_personality_match" in bad.json()["detail"]
    assert load_profile(root, person_id)["active_person_revision"] is None

    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json={
            "body_revision": "body-r0001",
            "voice_revision": "voice-r0001",
            "personality_revision": "personality-r0001",
            "body_voice_match": True,
            "voice_personality_match": True,
            "body_personality_match": True,
            "overall_coherent": True,
            "compatibility_note": "Krop, stemme og personality opleves som samme Anna.",
            "feedback": "first coherent person",
            "activate": True,
        },
    )
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["active_person_revision"] == "person-r0001"
    assert payload["person_revisions"][0]["body_revision"] == "body-r0001"
    assert payload["person_revisions"][0]["voice_revision"] == "voice-r0001"
    assert payload["person_revisions"][0]["personality_revision"] == "personality-r0001"


def test_new_personality_candidate_does_not_mutate_active_person(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None}).json()
    person_id = created["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)
    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json={
            "body_revision": "body-r0001",
            "voice_revision": "voice-r0001",
            "personality_revision": "personality-r0001",
            "body_voice_match": True,
            "voice_personality_match": True,
            "body_personality_match": True,
            "overall_coherent": True,
            "compatibility_note": "Version 1 hænger sammen.",
            "feedback": "v1",
            "activate": True,
        },
    )
    assert approved.status_code == 200

    candidate = client.post(
        f"/api/v1/people/{person_id}/personality/revisions",
        json={
            "instructions": "Du er Anna. Mere tør humor end før.",
            "default_language": "da",
            "style_notes": "mere tør",
            "feedback": "candidate only",
        },
    )
    assert candidate.status_code == 200
    payload = candidate.json()
    assert payload["active_person_revision"] == "person-r0001"
    assert len(payload["personality_revisions"]) == 2
    assert payload["person_revisions"][0]["personality_revision"] == "personality-r0001"
