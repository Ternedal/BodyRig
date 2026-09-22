from __future__ import annotations

import pytest

import bodyrig.high_fidelity_package_audit as audit
from bodyrig.fine_identity_application import build_requirement


def _fidelity(*, ready: bool = True) -> dict:
    return {
        "components": {
            "body_anatomy": "complete",
            "skin_appearance": "complete",
            "hair": "complete",
            "eyes": "complete",
            "face_secondary": "complete",
        },
        "high_fidelity_ready": ready,
        "top_level_blockers": [] if ready else ["skin_appearance"],
        "face_secondary_components": {},
        "face_secondary_ready": True,
        "face_secondary_blockers": [],
        "semantic_vertex_map_authority": "licensed-smplx-verified",
        "render_payloads": {},
        "human_review_required": True,
        "production_ready": False,
    }


def _requirement() -> dict:
    return build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256="c" * 64,
    )


def test_historical_package_without_requirement_keeps_existing_readiness() -> None:
    result = audit._apply_fine_identity_gate(
        _fidelity(),
        bodyrig={},
        avatar_vrm=b"historical-avatar",
    )
    assert result["high_fidelity_ready"] is True
    assert result["top_level_blockers"] == []
    assert result["fine_identity_required"] is False
    assert result["fine_identity_ready"] is True


def test_requirement_without_application_blocks_high_fidelity_ready() -> None:
    result = audit._apply_fine_identity_gate(
        _fidelity(),
        bodyrig={"fineIdentityRequirement": _requirement()},
        avatar_vrm=b"candidate-avatar",
    )
    assert result["high_fidelity_ready"] is False
    assert result["top_level_blockers"] == ["fine_identity"]
    assert result["fine_identity_required"] is True
    assert result["fine_identity_ready"] is False


def test_valid_application_preserves_existing_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = _requirement()
    application = {"opaque": "validated-by-contract-module"}

    monkeypatch.setattr(
        audit,
        "validate_fine_identity_application",
        lambda value, *, requirement, avatar_vrm: dict(value),
    )
    result = audit._apply_fine_identity_gate(
        _fidelity(),
        bodyrig={
            "fineIdentityRequirement": requirement,
            "fineIdentityApplication": application,
        },
        avatar_vrm=b"candidate-avatar",
    )
    assert result["high_fidelity_ready"] is True
    assert result["top_level_blockers"] == []
    assert result["fine_identity_required"] is True
    assert result["fine_identity_ready"] is True
    assert result["fine_identity"]["application"] == application


def test_application_without_requirement_is_rejected() -> None:
    with pytest.raises(audit.HighFidelityPackageAuditError, match="without a fine-identity requirement"):
        audit._apply_fine_identity_gate(
            _fidelity(),
            bodyrig={"fineIdentityApplication": {"unexpected": True}},
            avatar_vrm=b"candidate-avatar",
        )
