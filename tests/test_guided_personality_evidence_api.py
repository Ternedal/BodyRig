from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.guided_app as guided_app
from bodyrig.person_profiles import create_profile, load_profile
from bodyrig.personality_exemplar_approval import build_approval


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path, str]:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    monkeypatch.setattr(guided_app, "person_library", lambda: root)
    return TestClient(guided_app.app), root, profile["person_id"]


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["e" * 64],
        "candidate_count": 2,
        "candidates": ["Ja ja, det går nok.", "Nå, videre."],
        "suggested_exemplars": ["Ja ja, det går nok."],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _payload(report: dict, approval: dict) -> dict:
    return {
        "default_language": "da",
        "communication": {
            "directness": 0.7,
            "warmth": 0.6,
            "playfulness": 0.7,
            "formality": 0.2,
            "verbosity": 0.4,
            "initiative": 0.7,
        },
        "authored_notes": "",
        "style_exemplars": [],
        "style_report": report,
        "style_approval": approval,
        "body_revision": None,
    }


def test_preview_verifies_inline_report_and_approval(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/preview",
        json=_payload(report, approval),
    )

    assert response.status_code == 200
    value = response.json()
    assert value["style_evidence"]["approved_count"] == 1
    assert value["blueprint"]["style_exemplars"] == ["Ja ja, det går nok."]
    assert not (root / "personality-style-evidence").exists()


def test_save_persists_inline_style_evidence_and_candidate(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0, 1],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/revisions",
        json={**_payload(report, approval), "feedback": "browser evidence"},
    )

    assert response.status_code == 200
    value = response.json()
    assert value["style_evidence"]["approved_count"] == 2
    assert value["saved_personality_revision"] == "personality-r0001"
    assert (root / "personality-style-evidence" / person_id / "reports").is_dir()
    assert (root / "personality-style-evidence" / person_id / "approvals").is_dir()
    assert load_profile(root, person_id)["active_person_revision"] is None


def test_api_rejects_unpaired_or_tampered_evidence_without_mutation(tmp_path: Path, monkeypatch) -> None:
    client, root, person_id = _client(tmp_path, monkeypatch)
    report = _report()
    approval = build_approval(
        report,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    unpaired = _payload(report, approval)
    unpaired["style_approval"] = None
    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/revisions",
        json={**unpaired, "feedback": "bad"},
    )
    assert response.status_code == 422

    tampered = _payload(report, approval)
    tampered["style_report"] = dict(report)
    tampered["style_report"]["candidates"] = ["En anden replik.", "Nå, videre."]
    tampered["style_report"]["suggested_exemplars"] = ["Nå, videre."]
    response = client.post(
        f"/api/v1/people/{person_id}/personality/guided/revisions",
        json={**tampered, "feedback": "bad"},
    )
    assert response.status_code == 422
    assert load_profile(root, person_id)["personality_revisions"] == []
    assert not (root / "personality-style-evidence").exists()
