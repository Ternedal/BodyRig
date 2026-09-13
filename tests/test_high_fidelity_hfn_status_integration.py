from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_continuation_status as status


JOB_ID = "hfpreview-" + "a" * 32
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
REVISION = "b" * 40


def _legacy_complete(package: Path) -> dict:
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    return {
        "format": status.FORMAT,
        "version": status.VERSION,
        "preview_job_id": JOB_ID,
        "state": "complete",
        "gates": [status._gate(name, "pass") for name in status._legacy.GATE_ORDER],
        "next_gate": None,
        "current_package_path": str(package),
        "current_package_sha256": sha,
        "components": {"face_secondary": "complete"},
        "high_fidelity_complete": True,
        "high_fidelity_human_review_required": True,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": {"package_sha256": sha},
    }


def _preview_identity() -> dict:
    return {
        "person_id": PERSON,
        "body_revision": BODY,
        "bodyrig_revision": REVISION,
    }


def test_face_complete_cannot_be_high_fidelity_complete_before_hfn_candidate(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face.mrbody"
    face.write_bytes(b"face package")
    face_sha = hashlib.sha256(face.read_bytes()).hexdigest()
    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **kwargs: {
            "gates": [{
                "id": status.CANDIDATE_GATE,
                "state": "required",
                "passed": False,
                "reason": "no exact HFN detail candidate targets the face-secondary promoted package",
                "evidence": {},
            }],
            "actions": {
                status.CANDIDATE_GATE: {
                    "gate": status.CANDIDATE_GATE,
                    "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 ...",
                    "operator_input_required": True,
                    "reason": "select exact HFN source evidence",
                }
            },
            "package_path": face,
            "package_sha256": face_sha,
        },
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "incomplete"
    assert result["high_fidelity_complete"] is False
    assert result["high_fidelity_human_review_required"] is False
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert "prepare-hands-feet-nails-detail-candidate.ps1" in result["next_gate"]["command"]
    assert result["gates"][-1]["id"] == status.CANDIDATE_GATE
    assert result["production_activation"] is False


def test_hfn_reviewed_candidate_becomes_exact_final_package(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face.mrbody"
    face.write_bytes(b"face package")
    candidate = tmp_path / "candidate.mrbody"
    candidate.write_bytes(b"candidate package")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **kwargs: {
            "gates": [
                {"id": status.CANDIDATE_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
                {"id": status.RENDER_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
                {"id": status.HUMAN_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
            ],
            "actions": {},
            "package_path": candidate,
            "package_sha256": candidate_sha,
        },
    )
    components = {
        "body_anatomy": "complete",
        "skin_appearance": "complete",
        "hair": "complete",
        "eyes": "complete",
        "face_secondary": "complete",
    }
    monkeypatch.setattr(
        status,
        "audit_high_fidelity_package",
        lambda path: {
            "package_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "components": components,
            "high_fidelity_ready": True,
            "production_ready": False,
        },
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "complete"
    assert result["high_fidelity_complete"] is True
    assert result["current_package_path"] == str(candidate.resolve())
    assert result["current_package_sha256"] == candidate_sha
    assert [gate["id"] for gate in result["gates"][-3:]] == [
        status.CANDIDATE_GATE,
        status.RENDER_GATE,
        status.HUMAN_GATE,
    ]
    assert result["final_audit"]["package_sha256"] == candidate_sha
    assert result["production_ready"] is False
    assert result["production_activation"] is False


def test_hfn_candidate_final_audit_failure_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face.mrbody"
    face.write_bytes(b"face package")
    candidate = tmp_path / "candidate.mrbody"
    candidate.write_bytes(b"candidate package")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **kwargs: {
            "gates": [
                {"id": status.CANDIDATE_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
                {"id": status.RENDER_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
                {"id": status.HUMAN_GATE, "state": "pass", "passed": True, "reason": "", "evidence": {}},
            ],
            "actions": {},
            "package_path": candidate,
            "package_sha256": candidate_sha,
        },
    )
    monkeypatch.setattr(
        status,
        "audit_high_fidelity_package",
        lambda _path: {
            "package_sha256": candidate_sha,
            "components": {"face_secondary": "partial"},
            "high_fidelity_ready": False,
            "production_ready": False,
        },
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["high_fidelity_complete"] is False
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert result["next_gate"]["command"] is None
    candidate_gate = next(gate for gate in result["gates"] if gate["id"] == status.CANDIDATE_GATE)
    assert candidate_gate["state"] == "invalid"
    assert "final HFN candidate audit failed" in candidate_gate["reason"]
    assert result["production_activation"] is False