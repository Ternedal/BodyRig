from pathlib import Path

import pytest

from bodyrig.high_fidelity_package_audit import HighFidelityPackageAuditError
from bodyrig.person_release_status import PersonReleaseStatusError, _registered_fidelity_status

BODY_ID = "bodyid-" + "2" * 24
PACKAGE_SHA = "3" * 64


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


def test_registered_fidelity_status_exposes_exact_component_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", lambda _: _audit())

    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["state"] == "blocked"
    assert value["high_fidelity_ready"] is False
    assert value["components"]["hair"] == "missing"
    assert value["components"]["eyes"] == "partial"
    assert "hair" in value["blockers"]
    assert value["face_secondary"]["components"]["teeth"] == "missing"
    assert value["face_secondary"]["semantic_vertex_map_authority"] == "unavailable"
    assert value["production_ready"] is False


def test_registered_fidelity_status_can_report_component_complete_without_authorizing_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_placeholder(tmp_path, monkeypatch)
    monkeypatch.setattr("bodyrig.person_release_status.audit_high_fidelity_package", lambda _: _audit(ready=True))

    value = _registered_fidelity_status(body_id=BODY_ID, expected_sha=PACKAGE_SHA)

    assert value["state"] == "ready"
    assert value["high_fidelity_ready"] is True
    assert value["blockers"] == []
    assert value["face_secondary"]["ready"] is True
    assert value["human_review_required"] is True
    assert value["production_ready"] is False


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
    assert value["production_ready"] is False
    assert "fidelityComponents receipt is missing" in value["reason"]


def test_release_status_ui_uses_composite_production_gate_and_is_read_only() -> None:
    js = Path("bodyrig/ui/body_release_status.js").read_text(encoding="utf-8")

    assert "value.production_ready === true" in js
    assert "value.production_activation === true" in js
    assert "High-fidelity komponenter" in js
    assert "Anatomi" in js and "Hår" in js and "Øjne" in js and "Ansigtsdetaljer" in js
    assert "Øjenbryn" in js and "Mundinteriør" in js and "Tænder" in js and "Øjenvipper" in js
    assert "semantic_vertex_map_authority" in js
    assert 'method: "POST"' not in js
    assert "method: 'POST'" not in js
