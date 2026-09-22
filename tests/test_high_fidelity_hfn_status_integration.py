from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_continuation_status as status
from bodyrig.fine_identity_application import build_requirement


JOB_ID = "hfpreview-" + "a" * 32
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
REVISION = "b" * 40
CURRENT_HFN_REVISION = "c" * 40


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


def _components() -> dict[str, str]:
    return {
        "body_anatomy": "complete",
        "skin_appearance": "complete",
        "hair": "complete",
        "eyes": "complete",
        "face_secondary": "complete",
    }


def _fine_requirement() -> dict:
    return build_requirement(
        bodyrig_revision=REVISION,
        fine_identity_authority_sha256="1" * 64,
        fine_identity_attestation_sha256="2" * 64,
    )


def _fine_pending_audit(package: Path) -> dict:
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    return {
        "package_sha256": sha,
        "components": _components(),
        "high_fidelity_ready": False,
        "top_level_blockers": ["fine_identity"],
        "production_ready": False,
        "fine_identity_required": True,
        "fine_identity_ready": False,
        "fine_identity": {
            "requirement": _fine_requirement(),
            "application": None,
        },
    }


def _legacy_fine_pending(package: Path) -> dict:
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    gates = [status._gate(name, "pass") for name in status._legacy.GATE_ORDER]
    gates[-1] = status._gate(
        "face_secondary_promotion",
        "invalid",
        reason="all continuation gates passed but final package is not high-fidelity component complete",
    )
    return {
        "format": status.FORMAT,
        "version": status.VERSION,
        "preview_job_id": JOB_ID,
        "state": "blocked",
        "gates": gates,
        "next_gate": {
            "gate": "face_secondary_promotion",
            "command": None,
            "operator_input_required": False,
            "reason": gates[-1]["reason"],
        },
        "current_package_path": str(package),
        "current_package_sha256": sha,
        "components": _components(),
        "fine_identity_authority_sha256": "1" * 64,
        "fine_identity_attestation_sha256": "2" * 64,
        "high_fidelity_complete": False,
        "high_fidelity_human_review_required": False,
        "physical_windows_acceptance_required": True,
        "quest_acceptance_required": True,
        "final_release_required": True,
        "production_ready": False,
        "production_activation": False,
        "final_audit": _fine_pending_audit(package),
    }


def _preview_identity() -> dict:
    return {
        "person_id": PERSON,
        "body_revision": BODY,
        "bodyrig_revision": REVISION,
    }


def _install_current_hfn_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        status,
        "_integration_checkout_state",
        lambda: (CURRENT_HFN_REVISION, True, True),
    )


def test_face_complete_cannot_be_high_fidelity_complete_before_hfn_candidate(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face.mrbody"
    face.write_bytes(b"face package")
    face_sha = hashlib.sha256(face.read_bytes()).hexdigest()
    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_complete(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    _install_current_hfn_authority(monkeypatch)
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
    assert result["source_bodyrig_revision"] == REVISION
    assert result["hfn_bodyrig_revision"] == CURRENT_HFN_REVISION
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
    _install_current_hfn_authority(monkeypatch)
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
    components = _components()
    monkeypatch.setattr(
        status,
        "audit_high_fidelity_package",
        lambda path: {
            "package_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "components": components,
            "high_fidelity_ready": True,
            "top_level_blockers": [],
            "production_ready": False,
            "fine_identity_required": False,
            "fine_identity_ready": True,
            "fine_identity": None,
        },
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "complete"
    assert result["high_fidelity_complete"] is True
    assert result["current_package_path"] == str(candidate.resolve())
    assert result["current_package_sha256"] == candidate_sha
    assert result["source_bodyrig_revision"] == REVISION
    assert result["hfn_bodyrig_revision"] == CURRENT_HFN_REVISION
    assert [gate["id"] for gate in result["gates"][-4:]] == [
        status.CANDIDATE_GATE,
        status.RENDER_GATE,
        status.HUMAN_GATE,
        status.FINE_IDENTITY_GATE,
    ]
    assert result["gates"][-1]["state"] == "pass"
    assert result["gates"][-1]["evidence"]["required"] is False
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
    _install_current_hfn_authority(monkeypatch)
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
    assert result["source_bodyrig_revision"] == REVISION
    assert result["hfn_bodyrig_revision"] == CURRENT_HFN_REVISION
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert result["next_gate"]["command"] is None
    assert result["next_gate"]["operator_input_required"] is False
    candidate_gate = next(gate for gate in result["gates"] if gate["id"] == status.CANDIDATE_GATE)
    assert candidate_gate["state"] == "invalid"
    assert "final HFN candidate audit failed" in candidate_gate["reason"]
    assert result["production_activation"] is False

def test_fine_identity_only_pending_face_package_can_enter_hfn(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    face_sha = hashlib.sha256(face.read_bytes()).hexdigest()
    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_fine_pending(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda _path: _fine_pending_audit(face))
    _install_current_hfn_authority(monkeypatch)
    captured: dict[str, object] = {}

    def inspect_hfn(**kwargs):
        captured.update(kwargs)
        return {
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
        }

    monkeypatch.setattr(status, "inspect_hfn_continuation", inspect_hfn)

    result = status.inspect_continuation(JOB_ID)

    assert captured["source_package_path"] == face.resolve()
    assert captured["source_package_sha256"] == face_sha
    assert result["state"] == "incomplete"
    assert result["next_gate"]["gate"] == status.CANDIDATE_GATE
    assert result["high_fidelity_complete"] is False
    face_gate = next(
        gate for gate in result["gates"] if gate["id"] == "face_secondary_promotion"
    )
    assert face_gate["state"] == "pass"
    assert face_gate["evidence"]["fine_identity_pending"] is True
    assert result["production_activation"] is False


def test_fine_identity_handoff_rejects_origin_lineage_mismatch(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    base = _legacy_fine_pending(face)
    base["fine_identity_authority_sha256"] = "9" * 64

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: base)
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda _path: _fine_pending_audit(face))
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HFN must not run")),
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"]["gate"] == "face_secondary_promotion"
    assert result["high_fidelity_complete"] is False


def test_non_fine_identity_blocker_does_not_bypass_legacy_stop(monkeypatch, tmp_path: Path) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    base = _legacy_fine_pending(face)
    invalid_audit = _fine_pending_audit(face)
    invalid_audit["top_level_blockers"] = ["fine_identity", "hair"]

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: base)
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda _path: invalid_audit)
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HFN must not run")),
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"]["gate"] == "face_secondary_promotion"
    assert result["gates"][-1]["state"] == "invalid"
    assert result["high_fidelity_complete"] is False


def test_hfn_complete_photoidentical_package_stops_at_terminal_fine_identity_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    candidate = tmp_path / "hfn-photoidentical.mrbody"
    candidate.write_bytes(b"photoidentical HFN package")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_fine_pending(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: tmp_path / "preview")
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda path: _fine_pending_audit(path))
    _install_current_hfn_authority(monkeypatch)
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: {
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

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "incomplete"
    assert result["next_gate"]["gate"] == status.FINE_IDENTITY_GATE
    assert "apply-photoidentity-fine-identity.ps1" in result["next_gate"]["command"]
    assert "-SweepRoot <SWEEP_ROOT>" in result["next_gate"]["command"]
    assert "-AdapterConfig <ADAPTER_CONFIG>" in result["next_gate"]["command"]
    assert result["next_gate"]["operator_input_required"] is True
    assert result["high_fidelity_complete"] is False
    assert result["current_package_path"] == str(candidate.resolve())
    assert result["current_package_sha256"] == candidate_sha
    assert result["gates"][-1]["id"] == status.FINE_IDENTITY_GATE
    assert result["gates"][-1]["state"] == "required"
    assert result["gates"][-1]["evidence"]["fine_identity_authority_sha256"] == "1" * 64
    assert result["gates"][-1]["evidence"]["fine_identity_attestation_sha256"] == "2" * 64
    assert result["production_activation"] is False

def test_terminal_fine_identity_output_becomes_current_complete_package(
    monkeypatch,
    tmp_path: Path,
) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    candidate = tmp_path / "hfn-photoidentical.mrbody"
    candidate.write_bytes(b"photoidentical HFN package")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    preview_root = tmp_path / "preview"
    application_root = preview_root / "continuation" / "fine-identity-application"
    package_root = application_root / "package"
    package_root.mkdir(parents=True)
    applied = package_root / "applied.mrbody"
    applied.write_bytes(b"photoidentical applied package")
    applied_sha = hashlib.sha256(applied.read_bytes()).hexdigest()
    receipt = package_root / "application.json"
    receipt.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_fine_pending(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: preview_root)
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda path: _fine_pending_audit(path))
    _install_current_hfn_authority(monkeypatch)
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: {
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
    applied_audit = {
        "components": _components(),
        "high_fidelity_ready": True,
        "fine_identity_required": True,
        "fine_identity_ready": True,
        "top_level_blockers": [],
        "production_ready": False,
    }
    monkeypatch.setattr(
        status,
        "read_application_output",
        lambda *_args, **_kwargs: {
            "package_path": str(applied),
            "receipt_path": str(receipt),
            "applied_package_sha256": applied_sha,
            "audit": applied_audit,
        },
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "complete"
    assert result["next_gate"] is None
    assert result["current_package_path"] == str(applied.resolve())
    assert result["current_package_sha256"] == applied_sha
    assert result["high_fidelity_complete"] is True
    assert result["high_fidelity_human_review_required"] is True
    assert result["gates"][-1]["id"] == status.FINE_IDENTITY_GATE
    assert result["gates"][-1]["state"] == "pass"
    assert result["production_ready"] is False
    assert result["production_activation"] is False


def test_partial_terminal_fine_identity_output_blocks_without_overwrite_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    face = tmp_path / "face-photoidentical.mrbody"
    face.write_bytes(b"photoidentical face package")
    candidate = tmp_path / "hfn-photoidentical.mrbody"
    candidate.write_bytes(b"photoidentical HFN package")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    preview_root = tmp_path / "preview"
    (preview_root / "continuation" / "fine-identity-application").mkdir(parents=True)

    monkeypatch.setattr(status._legacy, "inspect_continuation", lambda _job: _legacy_fine_pending(face))
    monkeypatch.setattr(status._legacy.preview_manager, "get", lambda _job: _preview_identity())
    monkeypatch.setattr(status, "_preview_root", lambda _job: preview_root)
    monkeypatch.setattr(status, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(status, "audit_high_fidelity_package", lambda path: _fine_pending_audit(path))
    _install_current_hfn_authority(monkeypatch)
    monkeypatch.setattr(
        status,
        "inspect_hfn_continuation",
        lambda **_kwargs: {
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
        "read_application_output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            status.PhotoIdentityFineIdentityPackageError("persisted output is partial")
        ),
    )

    result = status.inspect_continuation(JOB_ID)

    assert result["state"] == "blocked"
    assert result["next_gate"]["gate"] == status.FINE_IDENTITY_GATE
    assert result["next_gate"]["command"] is None
    assert result["gates"][-1]["state"] == "invalid"
    assert "persisted output is partial" in result["next_gate"]["reason"]
    assert result["high_fidelity_complete"] is False
    assert result["production_activation"] is False

