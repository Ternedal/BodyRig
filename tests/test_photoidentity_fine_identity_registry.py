from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_fine_identity_registry as subject


def test_registry_contract_is_additive_and_fail_closed() -> None:
    assert subject.DIRNAME == "photoidentity-fine-identity-authority"
    assert subject.RECEIPT_NAME == "fine-identity-authority.json"
    assert subject.ATTESTATION_NAME == "fine-identity-source-attestation.json"


def test_require_rejects_missing_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job = {"person_id": "person-x"}
    monkeypatch.setattr(
        subject,
        "_job_authority",
        lambda body_job_id: (job, "42", "a" * 40, tmp_path, "b" * 64),
    )
    monkeypatch.setattr(subject, "require_body_job_photoidentity_evidence", lambda *args, **kwargs: {})
    with pytest.raises(subject.PhotoIdentityFineIdentityRegistryError, match="not registered"):
        subject.require_body_job_photoidentical_fine_identity("person-x", "job-" + "1" * 32)
