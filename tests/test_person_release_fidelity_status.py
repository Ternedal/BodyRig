from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.high_fidelity_package_audit import HighFidelityPackageAuditError
from bodyrig.person_release_status import (
    PersonReleaseStatusError,
    _registered_fidelity_status,
    inspect_candidate_release_status,
)

BODY_ID = "bodyid-" + "2" * 24
PACKAGE_SHA = "3" * 64
BODYRIG_REVISION = "4" * 40
PERSON_ID = "person-" + "5" * 32
BODY_REVISION = "body-r0001"


def _audit(*, ready: bool = False, package_sha: str = PACKAGE_SHA, body_id: str = BODY_ID) -> dict:
    components = {
        "body_anatomy": "complete" if ready else "not-evaluated",
        "skin_appearance": "complete" if ready else "partial",
        "hair": "complete" if ready else "missing",
        "eyes": "complete" if ready else "partial",
        "face_secondary": "complete" if ready else "missing",
    }
    face_components = {
        "eyebrow_appearance": "complete" if ready else "not-evaluated",
        "lip_boundary": "complete" if ready else "not-evaluated",
        "mouth_interior": "complete" if ready else "missing",
        "teeth": "complete" if ready else "missing",
        "eyelashes": "complete" if ready else "missing",
    }
    return {
        "canonical_body_id": body_id,
        "package_sha256": package_sha,
        "components": components,
        "high_fidelity_ready": ready,
        "top_level_blockers": [] if ready else [name for name, state in components.items() if state != "complete"],
        "face_secondary_components": face_components,
        "face_secondary_ready": ready,
        "face_secondary_blockers": [] if ready else [name for name, state in face_components.items() if state != "complete"],
        "semantic_vertex_map_authority": "licensed-smplx-verified" if ready else "unavailable",
        "human_review_required": True,
        "production_ready": False,
    }


def _install_placeholder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package = tmp_path / f"{BODY_ID}.mrbody"
    package.write_bytes(b"placeholder")
    monkeypatch.setattr("bodyrig.person_release_status.body_library", lambda: tmp_path)
    return package


def _human_review(*, passed: bool) -> dict:
    return {
        "state": "pass" if passed else "required",
        "passed": passed,
        "reason": None if passed else "Explicit high-fidelity human review is required for this exact package.",
        **({"reviewed_utc": "2026-09-02T14:00:00Z", "policy_revision": "bodyrig-high-fidelity-human-review-v1"} if passed else {}),
    }


def test_registered_fidelity_status_exposes_exact_component_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", lambda _: _audit())
    monkeypatch.setattr("bodyrig.person_release_status.fidelity_human_review_status", lambda _: _human_review(passed=False))

    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["state"] == "blocked"
    assert value["high_fidelity_ready"] is False
    assert value["components"]["hair"] == "missing"
    assert value["components"]["eyes"] == "partial"
    assert "hair" in value["blockers"]
    assert value["face_secondary"]["components"]["teeth"] == "missing"
    assert value["face_secondary"]["semantic_vertex_map_authority"] == "unavailable"
    assert value["human_review"]["passed"] is False
    assert value["production_ready"] is False


def test_component_complete_still_requires_explicit_human_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", lambda _: _audit(ready=True))
    monkeypatch.setattr("bodyrig.person_release_status.fidelity_human_review_status", lambda _: _human_review(passed=False))

    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["state"] == "ready"
    assert value["high_fidelity_ready"] is True
    assert value["blockers"] == []
    assert value["face_secondary"]["ready"] is True
    assert value["human_review_required"] is True
    assert value["human_review"]["state"] == "required"
    assert value["production_ready"] is False
    assert "human review is required" in value["reason"]


def test_component_complete_and_explicit_review_can_complete_fidelity_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", lambda _: _audit(ready=True))
    monkeypatch.setattr("bodyrig.person_release_status.fidelity_human_review_status", lambda _: _human_review(passed=True))

    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["high_fidelity_ready"] is True
    assert value["human_review"]["passed"] is True
    assert value["production_ready"] is True
    assert value["reason"] is None


def test_registered_fidelity_status_rejects_package_sha_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "bodyrig.person_release_status.audit_high_fidelity_package",
        lambda _: _audit(package_sha="9" * 64),
    )

    with pytest.raises(PersonReleaseStatusError, match="high-fidelity package SHA no longer matches"):
        _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)


def test_registered_fidelity_status_rejects_body_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "bodyrig.person_release_status.audit_high_fidelity_package",
        lambda _: _audit(body_id="different-body"),
    )

    with pytest.raises(PersonReleaseStatusError, match="high-fidelity package body id no longer matches"):
        _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)


def test_missing_or_invalid_fidelity_receipt_is_unavailable_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)

    def fail(_: Path) -> dict:
        raise HighFidelityPackageAuditError("BodyRig fidelityComponents receipt is missing")

    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", fail)
    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["state"] == "unavailable"
    assert value["high_fidelity_ready"] is False
    assert value["human_review"]["passed"] is False
    assert value["production_ready"] is False
    assert "fidelityComponents receipt is missing" in value["reason"]


def test_top_level_production_requires_physical_components_and_human_fidelity_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    status = AcceptanceStatus(
        state="complete",
        gate="release",
        acceptance_dir=str(acceptance),
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
        message="physical final release complete",
        next_command=None,
    )
    monkeypatch.setattr("bodyrig.person_release_status.inspect_acceptance_dir", lambda _: status)
    monkeypatch.setattr("bodyrig.person_release_status.apply_reference_policy", lambda value: value)
    monkeypatch.setattr("bodyrig.person_release_status._strict_platform_attestation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "bodyrig.person_release_status._read_json",
        lambda *_: {"package": {"body_id": BODY_ID, "package_sha256": PACKAGE_SHA}},
    )
    fidelity = {
        "state": "ready",
        "high_fidelity_ready": True,
        "human_review": _human_review(passed=False),
        "production_ready": False,
    }
    monkeypatch.setattr("bodyrig.person_release_status._registered_fidelity_status", lambda **_: fidelity)
    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "canonical_body_id": BODY_ID,
        "acceptance_dir": str(acceptance),
        "created_utc": "2026-09-02T14:00:00Z",
        "status": "succeeded",
    }

    blocked = inspect_candidate_release_status(
        [job],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert blocked["production_activation"] is True
    assert blocked["production_ready"] is False
    assert "explicit high-fidelity human review is still required" in blocked["message"]

    fidelity["human_review"] = _human_review(passed=True)
    fidelity["production_ready"] = True
    ready = inspect_candidate_release_status(
        [job],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=PACKAGE_SHA,
    )
    assert ready["production_activation"] is True
    assert ready["production_ready"] is True


def test_release_status_ui_uses_three_part_production_gate_and_is_read_only() -> None:
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")

    assert "value.production_ready === true" in js
    assert "value.production_activation === true" in js
    assert "value.fidelity?.human_review?.passed === true" in js
    assert "High-fidelity komponenter" in js
    assert "High-fidelity human review" in js
    assert "Review kræves" in js and "Review PASS" in js
    assert "Anatomi" in js and "Hår" in js and "Øjne" in js and "Ansigtsdetaljer" in js
    assert "Øjenbryn" in js and "Mundinteriør" in js and "Tænder" in js and "Øjenvipper" in js
    assert "semantic_vertex_map_authority" in js
    assert "tre uafhængige led" in js
    assert "record-high-fidelity-human-review.ps1" in js
    assert "-ConfirmQualityChecklist" in js
    assert "-QualityNote" in js
    assert "^[A-Za-z0-9._-]{3,160}$" in js
    assert "clean Git authority" in js
    assert 'method: "POST"' not in js
    assert "method: 'POST'" not in js
