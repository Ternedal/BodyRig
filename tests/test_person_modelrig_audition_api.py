from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
from bodyrig.execution_provenance import record_runtime
from bodyrig.person_audition import audio_path, read_audition
from bodyrig.person_profiles import (
    add_body_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
)


class FakeModelRig:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def health(self) -> dict:
        record_runtime("modelrig-server", "modelrig-test-runtime")
        return {"status": "ok", "service": "modelrig-server", "version": "modelrig-test-runtime"}

    def models(self) -> list[dict]:
        return [{"name": "fixture-model", "size": 123}]

    def chat(self, *, model: str, system: str, prompt: str) -> str:
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        return "Jeg er Anna. Tør nok til en integrationstest."


class FakeVoiceRig:
    package = b"fixture-mrvoice-package"

    def package_bytes(self, package: str) -> bytes:
        assert package == "anna.mrvoice"
        return self.package

    def synthesize(self, package: str, text: str) -> bytes:
        assert package == "anna.mrvoice"
        assert text == "Jeg er Anna. Tør nok til en integrationstest."
        record_runtime("voicerig", "voicerig-test-runtime")
        return b"RIFF" + b"\x00" * 80


def _profile(root: Path) -> dict:
    profile = create_profile(root, display_name="Anna")
    person_id = profile["person_id"]
    add_body_revision(
        root,
        person_id,
        body_id="bodyid-0123456789abcdef01234567",
        package_sha256="a" * 64,
        package_path=str(root / "anna.mrbody"),
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="anna-voice",
        voice_package="anna.mrvoice",
        package_sha256=hashlib.sha256(FakeVoiceRig.package).hexdigest(),
    )
    return add_personality_revision(
        root,
        person_id,
        instructions="Du er Anna. Svar roligt, kort og med tør humor.",
        default_language="da",
        style_notes="tør, rolig",
    )


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, dict, FakeModelRig]:
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(app_module, "person_library", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_body_bytes_match", lambda item: Path(item["package_path"]))
    monkeypatch.setattr(app_module, "_voice_bytes_match", lambda item, client: None)
    fake_modelrig = FakeModelRig()
    monkeypatch.setattr(app_module, "_modelrig_client", lambda: fake_modelrig)
    monkeypatch.setattr(app_module, "_voicerig_client", lambda: FakeVoiceRig())
    profile = _profile(tmp_path)
    return TestClient(app_module.app), profile, fake_modelrig


def test_modelrig_reply_is_synthesized_and_runtime_bound_to_approved_person_revision(tmp_path: Path, monkeypatch) -> None:
    client, profile, modelrig = _client(tmp_path, monkeypatch)
    person_id = profile["person_id"]
    selection = {
        "body_revision": "body-r0001",
        "voice_revision": "voice-r0001",
        "personality_revision": "personality-r0001",
    }

    prepared = client.post(f"/api/v1/people/{person_id}/assembly", json=selection)
    assert prepared.status_code == 200
    fingerprint = prepared.json()["assembly_fingerprint"]

    audition = client.post(
        f"/api/v1/people/{person_id}/auditions",
        json={**selection, "model": "fixture-model", "prompt": "Præsenter dig selv kort."},
    )
    assert audition.status_code == 200
    evidence = audition.json()
    assert evidence["assembly_fingerprint"] == fingerprint
    assert evidence["reply"] == "Jeg er Anna. Tør nok til en integrationstest."
    assert evidence["audition_id"].startswith("audition-")
    assert modelrig.calls == [{
        "model": "fixture-model",
        "system": "Du er Anna. Svar roligt, kort og med tør humor.\n\nStyle notes:\ntør, rolig\n\nDefault language: da. Reply in this language unless the user explicitly asks for another language.",
        "prompt": "Præsenter dig selv kort.",
    }]
    receipt = read_audition(tmp_path, person_id=person_id, audition_id=evidence["audition_id"])
    assert receipt["modelrig_service"] == "modelrig-server"
    assert receipt["modelrig_version"] == "modelrig-test-runtime"
    assert receipt["voicerig_service"] == "voicerig"
    assert receipt["voicerig_version"] == "voicerig-test-runtime"

    audio = client.get(evidence["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content.startswith(b"RIFF")

    approved = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json={
            **selection,
            "assembly_fingerprint": fingerprint,
            "audition_id": evidence["audition_id"],
            "body_voice_match": True,
            "voice_personality_match": True,
            "body_personality_match": True,
            "overall_coherent": True,
            "compatibility_note": "Krop, ModelRig-svar og VoiceRig-stemme opleves som samme person.",
            "feedback": "første faktisk udførte personality-audition",
            "activate": True,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["active_person_revision"] == "person-r0001"

    wav = audio_path(tmp_path, person_id, evidence["audition_id"])
    wav.write_bytes(wav.read_bytes() + b"tamper")
    reactivation = client.post(f"/api/v1/people/{person_id}/revisions/person-r0001/activate")
    assert reactivation.status_code == 409
    assert "audio" in reactivation.json()["detail"].lower()


def test_audition_for_one_assembly_cannot_approve_another(tmp_path: Path, monkeypatch) -> None:
    client, profile, _ = _client(tmp_path, monkeypatch)
    person_id = profile["person_id"]
    first = {
        "body_revision": "body-r0001",
        "voice_revision": "voice-r0001",
        "personality_revision": "personality-r0001",
    }
    prepared = client.post(f"/api/v1/people/{person_id}/assembly", json=first).json()
    audition = client.post(
        f"/api/v1/people/{person_id}/auditions",
        json={**first, "model": "fixture-model", "prompt": "Hej"},
    ).json()

    add_personality_revision(tmp_path, person_id, instructions="Du er Anna version to.", default_language="da")
    changed = {**first, "personality_revision": "personality-r0002"}
    response = client.post(
        f"/api/v1/people/{person_id}/revisions",
        json={
            **changed,
            "assembly_fingerprint": prepared["assembly_fingerprint"],
            "audition_id": audition["audition_id"],
            "body_voice_match": True,
            "voice_personality_match": True,
            "body_personality_match": True,
            "overall_coherent": True,
            "compatibility_note": "må ikke accepteres",
            "feedback": "",
            "activate": True,
        },
    )
    assert response.status_code == 409
    assert "changed after audition" in response.json()["detail"]
