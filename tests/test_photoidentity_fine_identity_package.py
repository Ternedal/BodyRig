from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

import bodyrig.photoidentity_fine_identity_package as subject
from bodyrig.fine_identity_application import REQUIRED_DOMAINS


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _attestation() -> dict[str, object]:
    selected = []
    for domain in REQUIRED_DOMAINS:
        selected.extend(
            [
                {"domain": domain, "reference": f"{domain}-1"},
                {"domain": domain, "reference": f"{domain}-2"},
            ]
        )
    return {
        "selected_evidence": selected,
        "marker_inventory_sha256": "f" * 64,
    }


def _reconstruction_refs() -> dict[str, list[str]]:
    return {
        domain: [f"{domain}-1", f"{domain}-2"]
        for domain in REQUIRED_DOMAINS
        if domain != "oral_teeth_detail"
    }


def test_application_domains_bind_exact_dental_and_reconstruction_lineage() -> None:
    domains = subject._application_domains(
        attestation=_attestation(),
        reconstruction_references=_reconstruction_refs(),
        dental_references=["oral_teeth_detail-1", "oral_teeth_detail-2"],
    )
    assert set(domains) == set(REQUIRED_DOMAINS)
    assert domains["oral_teeth_detail"] == {
        "sourceEvidenceCount": 2,
        "geometryApplied": True,
        "appearanceApplied": True,
    }
    assert domains["nipple_areola_detail"]["geometryApplied"] is False
    assert domains["nipple_areola_detail"]["appearanceApplied"] is True


def test_application_domains_reject_dental_lineage_drift() -> None:
    with pytest.raises(
        subject.PhotoIdentityFineIdentityPackageError,
        match="lost exact source-derived dental reference lineage",
    ):
        subject._application_domains(
            attestation=_attestation(),
            reconstruction_references=_reconstruction_refs(),
            dental_references=["oral_teeth_detail-2", "oral_teeth_detail-1"],
        )


def test_materialize_application_requires_final_non_production_readiness(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_package = tmp_path / "source.mrbody"
    source_package.write_bytes(b"source-package")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("attestation", encoding="utf-8")
    candidate = tmp_path / "candidate.vrm"
    candidate.write_bytes(b"candidate")
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text("input", encoding="utf-8")
    result_path = tmp_path / "result.json"
    result_path.write_text("result", encoding="utf-8")

    attestation_sha = _sha(attestation_path.read_bytes())
    source_avatar = b"source-avatar"
    prepared = {
        "canonical_body_id": "body-1",
        "operator_bodyrig_revision": "a" * 40,
        "requirement_bodyrig_revision": "b" * 40,
        "fine_identity_authority_sha256": "c" * 64,
        "fine_identity_attestation_sha256": attestation_sha,
        "source_package_sha256": _sha(source_package.read_bytes()),
        "source_avatar_sha256": _sha(source_avatar),
        "marker_inventory_sha256": "f" * 64,
        "source_references": _reconstruction_refs(),
    }
    monkeypatch.setattr(
        subject,
        "read_reconstruction_workspace",
        lambda **_kwargs: {
            "prepared": prepared,
            "candidate_vrm_path": str(candidate),
            "input_manifest_path": str(input_manifest),
            "result_path": str(result_path),
        },
    )
    requirement = {
        "bodyrigRevision": "b" * 40,
        "fineIdentityAuthoritySha256": "c" * 64,
        "fineIdentityAttestationSha256": attestation_sha,
    }
    monkeypatch.setattr(
        subject,
        "_source_authority",
        lambda _path: (requirement, source_avatar, "body-1"),
    )
    monkeypatch.setattr(
        subject,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": "body-1"}),
    )
    monkeypatch.setattr(
        subject,
        "read_attestation",
        lambda *_args, **_kwargs: {
            **_attestation(),
            "marker_inventory_sha256": "f" * 64,
        },
    )

    application = {"application": "exact"}
    monkeypatch.setattr(
        subject,
        "_embed_application",
        lambda **_kwargs: (b"applied-avatar", application),
    )

    source_audit = {
        "render_payloads": {
            "face_secondary": {
                "source_dental": {
                    "source_references": [
                        "oral_teeth_detail-1",
                        "oral_teeth_detail-2",
                    ]
                }
            }
        }
    }
    final_audit = {
        "canonical_body_id": "body-1",
        "fine_identity_required": True,
        "fine_identity_ready": True,
        "high_fidelity_ready": True,
        "top_level_blockers": [],
        "components": {"anatomy": "complete", "hair": "complete", "eyes": "complete", "face_secondary": "complete"},
        "production_ready": False,
        "fine_identity": {"application": application},
    }
    monkeypatch.setattr(
        subject,
        "audit_high_fidelity_package",
        lambda path: source_audit if path == source_package.resolve() else final_audit,
    )

    def rewrite(_source, destination, *, avatar_vrm):
        assert avatar_vrm == b"applied-avatar"
        destination.write_bytes(b"applied-package")

    monkeypatch.setattr(subject, "_rewrite_package", rewrite)

    result = subject.materialize_application(
        source_package_path=source_package,
        reconstruction_workspace=workspace,
        config_path=config,
        attestation_path=attestation_path,
        output_dir=tmp_path / "out",
    )
    assert result["package_application_authority"] is True
    assert result["human_review_required"] is True
    assert result["production_activation"] is False
    assert result["application"] == application
    assert result["audit"]["fine_identity_ready"] is True
