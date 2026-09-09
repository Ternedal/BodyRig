from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.body_job_receipt_authority as authority
from bodyrig.pbr_ab_body_job_source import PbrAbBodyJobSourceError


JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
OTHER_PERSON_ID = "person-" + "3" * 32
REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict]:
    data = tmp_path / "data"
    monkeypatch.setenv("BODYRIG_DATA_DIR", str(data))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    job_root = data / "ui-jobs" / JOB_ID
    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "status": "succeeded",
        "person_id": PERSON_ID,
        "bodyrig_revision": REVISION,
        "body_revision": "body-r0001",
        "canonical_body_id": "canonical-body",
        "source_binding_sha256": "c" * 64,
        "body_review_sha256": "d" * 64,
    }
    _write_json(job_root / "job.json", job)

    source_binding = tmp_path / "source-binding.json"
    _write_json(
        source_binding,
        {
            "evidence": {
                "kind": "stash-physical-source-manifest-v1",
                "sha256": "e" * 64,
            },
            "component": {
                "artifact_sha256": "f" * 64,
            },
        },
    )
    review = tmp_path / "review.json"
    _write_json(review, {"format": "fixture"})

    persisted = {
        "body_revision": "body-r0001",
        "canonical_body_id": "canonical-body",
        "source_binding": str(source_binding),
        "source_binding_sha256": "c" * 64,
        "body_review": str(review),
        "body_review_sha256": "d" * 64,
    }
    monkeypatch.setattr(authority, "_verify_persisted_receipts", lambda **_kwargs: dict(persisted))
    return job_root, source_binding, job


def test_succeeded_body_job_receipt_authority_binds_source_and_review(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    result = authority.inspect_succeeded_body_job_receipts(
        job_id=JOB_ID,
        expected_revision=REVISION,
        expected_person_id=PERSON_ID,
    )

    assert result["format"] == authority.FORMAT
    assert result["body_job_id"] == JOB_ID
    assert result["person_id"] == PERSON_ID
    assert result["bodyrig_revision"] == REVISION
    assert result["body_revision"] == "body-r0001"
    assert result["canonical_body_id"] == "canonical-body"
    assert result["package_sha256"] == "f" * 64
    assert result["source_binding_sha256"] == "c" * 64
    assert result["body_review_sha256"] == "d" * 64
    assert result["source_evidence_kind"] == "stash-physical-source-manifest-v1"
    assert result["source_evidence_sha256"] == "e" * 64
    assert len(result["job_json_sha256"]) == 64
    assert result["comparison_only"] is True
    assert result["human_visual_authority_required"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False


def test_receipt_authority_rejects_wrong_expected_revision(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="not expected revision"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=OTHER_REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_rejects_wrong_expected_person(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="Person does not match"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=OTHER_PERSON_ID,
        )


def test_receipt_authority_requires_canonical_stash_physical_manifest(tmp_path: Path, monkeypatch) -> None:
    _job_root, source_binding, _job = _setup(tmp_path, monkeypatch)
    _write_json(
        source_binding,
        {
            "evidence": {"kind": "other-evidence", "sha256": "e" * 64},
            "component": {"artifact_sha256": "f" * 64},
        },
    )

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="canonical Stash physical source manifest"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_propagates_persisted_receipt_tamper_failure(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    def _tampered(**_kwargs):
        raise PbrAbBodyJobSourceError("registered body source binding receipt changed after body job success")

    monkeypatch.setattr(authority, "_verify_persisted_receipts", _tampered)
    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="changed after body job success"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )
