from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.guided_app as guided_app
from bodyrig.person_assembly import build_assembly
from bodyrig.person_audition import write_audition
from bodyrig.person_profiles import (
    add_body_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    load_profile,
)
from bodyrig.personality_audition_suite import build_audition_suite

RUNTIME = {
    "modelrig_service": "modelrig-server",
    "modelrig_version": "modelrig-test-1",
    "voicerig_service": "voicerig",
    "voicerig_version": "voicerig-test-1",
}


def _profile(root: Path) -> dict:
    profile = create_profile(root, display_name="Anna")
    person_id = profile["person_id"]
    add_body_revision(
        root,
        person_id,
        body_id="anna-body-0001",
        package_sha256="a" * 64,
        package_path=r"C:\BodyRig\anna.mrbody",
        feedback="fixture",
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="anna-voice-0001",
        voice_package="anna.mrvoice",
        package_sha256="b" * 64,
        feedback="fixture",
    )
    return add_personality_revision(
        root,
        person_id,
        instructions="Du er Anna. Vær naturlig og opfind ikke minder.",
        default_language="da",
        style_notes="rolig og tør",
        feedback="fixture",
    )


def _auditions(root: Path, profile: dict) -> tuple[dict, dict[str, str]]:
    assembly = build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )
    ids: dict[str, str] = {}
    for probe in build_audition_suite("da")["probes"]:
        receipt = write_audition(
            root,
            person_id=profile["person_id"],
            assembly_fingerprint=assembly["assembly_fingerprint"],
            model="fixture-model",
            prompt=probe["prompt"],
            reply=f"Svar på {probe['id']}",
            audio=b"RIFF" + bytes([len(ids)]) + b"\x00" * 63,
            **RUNTIME,
        )
        ids[probe["id"]] = receipt["audition_id"]
    return assembly, ids


def test_suite_api_exposes_definition_and_seals_non_authoritative_review(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "people"
    profile = _profile(root)
    assembly, ids = _auditions(root, profile)
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(guided_app, "person_library", lambda: root)
    client = TestClient(guided_app.app)

    suite = client.get("/api/v1/personality/audition-suite?language=da")
    assert suite.status_code == 200
    assert len(suite.json()["probes"]) == 6
    assert suite.json()["activation_authority"] is False

    sealed = client.post(
        f"/api/v1/people/{profile['person_id']}/personality/audition-suite/reviews",
        json={
            "body_revision": "body-r0001",
            "voice_revision": "voice-r0001",
            "personality_revision": "personality-r0001",
            "assembly_fingerprint": assembly["assembly_fingerprint"],
            "model": "fixture-model",
            "default_language": "da",
            "audition_ids": ids,
        },
    )
    assert sealed.status_code == 200
    payload = sealed.json()
    assert len(payload["review_sha256"]) == 64
    assert payload["review"]["human_review_required"] is True
    assert payload["review"]["activation_authority"] is False
    assert load_profile(root, profile["person_id"])["active_person_revision"] is None

    checked = client.get(
        f"/api/v1/people/{profile['person_id']}/personality/audition-suite/reviews/{payload['review']['review_id']}"
    )
    assert checked.status_code == 200
    assert checked.json()["review_sha256"] == payload["review_sha256"]


def test_suite_api_rejects_partial_evidence_without_writing_review(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "people"
    profile = _profile(root)
    assembly, ids = _auditions(root, profile)
    ids.pop("unknown-memory-boundary")
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(guided_app, "person_library", lambda: root)
    client = TestClient(guided_app.app)

    response = client.post(
        f"/api/v1/people/{profile['person_id']}/personality/audition-suite/reviews",
        json={
            "body_revision": "body-r0001",
            "voice_revision": "voice-r0001",
            "personality_revision": "personality-r0001",
            "assembly_fingerprint": assembly["assembly_fingerprint"],
            "model": "fixture-model",
            "default_language": "da",
            "audition_ids": ids,
        },
    )
    assert response.status_code == 422
    assert "exact suite probe ids" in response.json()["detail"]
    review_root = root / "personality-suite-reviews" / profile["person_id"]
    assert not review_root.exists()
