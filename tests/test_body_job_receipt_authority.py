from __future__ import annotations

import hashlib
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
STASH_PERFORMER_ID = "42"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, dict]:
    data = tmp_path / "data"
    monkeypatch.setenv("BODYRIG_DATA_DIR", str(data))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    media = tmp_path / "source.mp4"
    media.write_bytes(b"fixture source bytes")
    manifest = tmp_path / "bodyrig-stash-source-manifest.json"
    _write_json(
        manifest,
        {
            "format": "bodyrig-stash-source-manifest",
            "version": 1,
            "performer": {"id": STASH_PERFORMER_ID, "name": "Fixture"},
            "selected": [{"scene_id": "scene-1", "path": str(media)}],
        },
    )

    source_binding = tmp_path / "source-binding.json"
    _write_json(
        source_binding,
        {
            "source": {"performer_id": STASH_PERFORMER_ID},
            "evidence": {
                "kind": "stash-physical-source-manifest-v1",
                "sha256": _file_sha(manifest),
                "ref": str(manifest),
                "source_files": [
                    {"scene_id": "scene-1", "name": media.name, "sha256": "9" * 64},
                ],
            },
            "component": {"artifact_sha256": "f" * 64},
        },
    )
    review = tmp_path / "review.json"
    _write_json(review, {"format": "fixture"})

    job_root = data / "ui-jobs" / JOB_ID
    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "status": "succeeded",
        "person_id": PERSON_ID,
        "bodyrig_revision": REVISION,
        "source_enqueue_authority": {
            "format": "bodyrig-body-build-source-enqueue-authority",
            "version": 1,
            "job_id": JOB_ID,
            "person_id": PERSON_ID,
            "stash_performer_id": STASH_PERFORMER_ID,
            "expected_bodyrig_revision": REVISION,
        },
        "body_revision": "body-r0001",
        "canonical_body_id": "canonical-body",
        "source_binding_sha256": _file_sha(source_binding),
        "body_review_sha256": _file_sha(review),
    }
    _write_json(job_root / "job.json", job)

    persisted = {
        "body_revision": "body-r0001",
        "canonical_body_id": "canonical-body",
        "source_binding": str(source_binding),
        "source_binding_sha256": _file_sha(source_binding),
        "body_review": str(review),
        "body_review_sha256": _file_sha(review),
    }
    monkeypatch.setattr(authority, "_verify_persisted_receipts", lambda **_kwargs: dict(persisted))
    return job_root, source_binding, manifest, job


def test_succeeded_body_job_receipt_authority_binds_source_and_review(tmp_path: Path, monkeypatch) -> None:
    _job_root, source_binding, manifest, _job = _setup(tmp_path, monkeypatch)

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
    assert result["source_binding_sha256"] == _file_sha(source_binding)
    assert result["stash_performer_id"] == STASH_PERFORMER_ID
    assert result["source_evidence_kind"] == "stash-physical-source-manifest-v1"
    assert result["source_evidence_sha256"] == _file_sha(manifest)
    assert len(result["source_files_sha256"]) == 64
    assert len(result["body_review_sha256"]) == 64
    assert len(result["job_json_sha256"]) == 64
    assert result["comparison_only"] is True
    assert result["human_visual_authority_required"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False


def test_receipt_authority_rejects_missing_source_enqueue_authority(tmp_path: Path, monkeypatch) -> None:
    job_root, _source_binding, _manifest, job = _setup(tmp_path, monkeypatch)
    job.pop("source_enqueue_authority")
    _write_json(job_root / "job.json", job)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="lacks canonical revision-bound source enqueue authority"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_rejects_enqueue_performer_different_from_success_source(tmp_path: Path, monkeypatch) -> None:
    job_root, _source_binding, _manifest, job = _setup(tmp_path, monkeypatch)
    job["source_enqueue_authority"]["stash_performer_id"] = "84"
    _write_json(job_root / "job.json", job)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="source binding performer differs from revision-bound source enqueue authority"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


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
    _job_root, source_binding, manifest, _job = _setup(tmp_path, monkeypatch)
    value = json.loads(source_binding.read_text(encoding="utf-8"))
    value["evidence"]["kind"] = "other-evidence"
    _write_json(source_binding, value)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="canonical Stash physical source manifest"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )
    assert manifest.is_file()


def test_receipt_authority_rejects_source_manifest_byte_drift(tmp_path: Path, monkeypatch) -> None:
    _job_root, _source_binding, manifest, _job = _setup(tmp_path, monkeypatch)
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="source manifest bytes changed"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_rejects_source_file_receipt_selection_drift(tmp_path: Path, monkeypatch) -> None:
    _job_root, source_binding, _manifest, _job = _setup(tmp_path, monkeypatch)
    value = json.loads(source_binding.read_text(encoding="utf-8"))
    value["evidence"]["source_files"][0]["name"] = "different.mp4"
    _write_json(source_binding, value)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="no longer matches source manifest selection"):
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