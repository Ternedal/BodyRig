from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
from bodyrig.execution_provenance import record_runtime
from bodyrig.person_assembly import read_receipt
from bodyrig.person_profiles import add_body_revision, load_profile

VOICE_BYTES = b"fixture-mrvoice-bytes"


class _FakeVoiceRig:
    def __init__(self) -> None:
        self.package_raw = VOICE_BYTES

    def health(self):
        record_runtime("voicerig", "test")
        return {"ok": True, "service": "voicerig", "version": "test"}

    def voices(self):
        return [{"id": "anna-voice-0001", "name": "Anna", "language": "da", "package": "anna.mrvoice", "is_default": False, "compatibility": {}}]

    def package_bytes(self, package: str) -> bytes:
        assert package == "anna.mrvoice"
        return self.package_raw

    def preview(self, package: str) -> bytes:
        assert package == "anna.mrvoice"
        return b"RIFF" + b"\x00" * 64

    def synthesize(self, package: str, text: str) -> bytes:
        assert package == "anna.mrvoice"
        assert text
        self.health()
        return b"RIFF" + b"\x00" * 64


class _FakeModelRig:
    def health(self):
        record_runtime("modelrig-server", "test")
        return {"status": "ok", "service": "modelrig-server", "version": "test"}

    def models(self):
        return [{"name": "fixture-model", "size": 1}]

    def chat(self, *, model: str, system: str, prompt: str) -> str:
        assert model == "fixture-model"
        assert system and prompt
        return "Jeg er Anna; dette er den faktisk udførte personality."


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, _FakeVoiceRig]:
    people = tmp_path / "people"
    voice = _FakeVoiceRig()
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(app_module, "person_library", lambda: people)
    monkeypatch.setattr(app_module, "_voicerig_client", lambda: voice)
    monkeypatch.setattr(app_module, "_modelrig_client", lambda: _FakeModelRig())
    monkeypatch.setattr(app_module, "_body_bytes_match", lambda item: Path(item["package_path"]))
    return TestClient(app_module.app), voice


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
        json={"voice_package": "anna.mrvoice", "feedback": "voice candidate"},
    )
    assert voice.status_code == 200
    voice_item = voice.json()["voice_revisions"][0]
    assert voice_item["voice_id"] == "anna-voice-0001"
    assert voice_item["voice_package"] == "anna.mrvoice"
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


def _selection(personality: str = "personality-r0001") -> dict:
    return {
        "body_revision": "body-r0001",
        "voice_revision": "voice-r0001",
        "personality_revision": personality,
    }


def _assembly(client: TestClient, person_id: str, personality: str = "personality-r0001") -> dict:
    response = client.post(f"/api/v1/people/{person_id}/assembly", json=_selection(personality))
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["assembly_fingerprint"]) == 64
    assert payload["voice"]["voice_package"] == "anna.mrvoice"
    assert payload["personality_preview"]["instructions"].startswith("Du er Anna")
    return payload


def _audition(client: TestClient, person_id: str, personality: str = "personality-r0001") -> dict:
    response = client.post(
        f"/api/v1/people/{person_id}/auditions",
        json={**_selection(personality), "model": "fixture-model", "prompt": "Præsenter dig selv kort."},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["audition_id"].startswith("audition-")
    assert payload["reply"].startswith("Jeg er Anna")
    return payload


def _approval_payload(fingerprint: str, audition_id: str, *, personality: str = "personality-r0001") -> dict:
    return {
        **_selection(personality),
        "assembly_fingerprint": fingerprint,
        "audition_id": audition_id,
        "body_voice_match": True,
        "voice_personality_match": True,
        "body_personality_match": True,
        "overall_coherent": True,
        "compatibility_note": "Krop, stemme og faktisk ModelRig-personality opleves som samme Anna.",
        "feedback": "first coherent person",
        "activate": True,
    }


def test_components_remain_candidates_until_exact_assembly_is_reviewed(tmp_path: Path, monkeypatch) -> None:
    client, _voice = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None})
    assert created.status_code == 200
    person_id = created.json()["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)

    profile = load_profile(root, person_id)
    assert profile["active_person_revision"] is None

    old_path = client.post(f"/api/v1/people/{person_id}/activate/body/body-r0001")
    assert old_path.status_code == 409

    assembly = _assembly(client, person_id)
    audition = _audition(client, person_id)
    assert audition["assembly_fingerprint"] == assembly["assembly_fingerprint"]
    bad = _approval_payload(assembly["assembly_fingerprint"], audition["audition_id"])
    bad["voice_personality_match"] = False
    rejected = client.post(f"/api/v1/people/{person_id}/revisions", json=bad)
    assert rejected.status_code == 422
    assert "voice_personality_match" in rejected.json()["detail"]
    assert load_profile(root, person_id)["active_person_revision"] is None

    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json=_approval_payload(assembly["assembly_fingerprint"], audition["audition_id"]),
    )
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["active_person_revision"] == "person-r0001"
    receipt = read_receipt(root, person_id=person_id, person_revision="person-r0001")
    assert receipt["version"] == 2
    assert receipt["assembly_fingerprint"] == assembly["assembly_fingerprint"]
    assert receipt["body"]["revision_id"] == "body-r0001"
    assert receipt["voice"]["revision_id"] == "voice-r0001"
    assert receipt["personality"]["revision_id"] == "personality-r0001"
    assert receipt["audition"]["audition_id"] == audition["audition_id"]


def test_old_fingerprint_cannot_approve_a_different_component_combination(tmp_path: Path, monkeypatch) -> None:
    client, _voice = _client(tmp_path, monkeypatch)
    person_id = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None}).json()["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)
    first = _assembly(client, person_id)
    audition = _audition(client, person_id)
    second_personality = client.post(
        f"/api/v1/people/{person_id}/personality/revisions",
        json={
            "instructions": "Du er Anna v2. Mere direkte og mere tør.",
            "default_language": "da",
            "style_notes": "direkte",
            "feedback": "candidate 2",
        },
    )
    assert second_personality.status_code == 200
    wrong = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json=_approval_payload(first["assembly_fingerprint"], audition["audition_id"], personality="personality-r0002"),
    )
    assert wrong.status_code == 409
    assert "changed after audition" in wrong.json()["detail"]
    assert load_profile(root, person_id)["active_person_revision"] is None


def test_voice_bytes_must_still_match_during_audition_and_activation(tmp_path: Path, monkeypatch) -> None:
    client, voice = _client(tmp_path, monkeypatch)
    person_id = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None}).json()["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)
    assembly = _assembly(client, person_id)
    audition = _audition(client, person_id)
    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json=_approval_payload(assembly["assembly_fingerprint"], audition["audition_id"]),
    )
    assert approved.status_code == 200

    voice.package_raw = b"changed-under-same-name"
    preview = client.get(f"/api/v1/people/{person_id}/voice/preview?revision=voice-r0001")
    assert preview.status_code == 409
    reactivate = client.post(f"/api/v1/people/{person_id}/revisions/person-r0001/activate")
    assert reactivate.status_code == 409
    assert "VoiceRig package bytes" in reactivate.json()["detail"]


def test_new_personality_candidate_does_not_mutate_active_person(tmp_path: Path, monkeypatch) -> None:
    client, _voice = _client(tmp_path, monkeypatch)
    person_id = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None}).json()["person_id"]
    root = app_module.person_library()
    _create_components(client, root, person_id)
    assembly = _assembly(client, person_id)
    audition = _audition(client, person_id)
    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json=_approval_payload(assembly["assembly_fingerprint"], audition["audition_id"]),
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


def test_voice_preview_and_synthesis_are_bound_to_registered_package_bytes(tmp_path: Path, monkeypatch) -> None:
    client, _voice = _client(tmp_path, monkeypatch)
    person_id = client.post("/api/v1/people", json={"display_name": "Anna", "aliases": [], "stash_performer": None}).json()["person_id"]
    voice = client.post(f"/api/v1/people/{person_id}/voice/revisions", json={"voice_package": "anna.mrvoice", "feedback": "audition"})
    assert voice.status_code == 200

    preview = client.get(f"/api/v1/people/{person_id}/voice/preview?revision=voice-r0001")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("audio/wav")

    synthesized = client.post(
        f"/api/v1/people/{person_id}/voice/synthesize",
        json={"revision": "voice-r0001", "text": "Hej, det er Anna."},
    )
    assert synthesized.status_code == 200
    assert synthesized.content.startswith(b"RIFF")
