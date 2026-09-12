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
BODY_REVISION = "body-r0001"
PACKAGE_SHA = "f" * 64
_REAL_VERIFY_PERSISTED_RECEIPTS = authority._verify_persisted_receipts


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
            "component": {"artifact_sha256": PACKAGE_SHA},
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
        "body_revision": BODY_REVISION,
        "canonical_body_id": "canonical-body",
        "source_binding_sha256": _file_sha(source_binding),
        "body_review_sha256": _file_sha(review),
    }
    _write_json(job_root / "job.json", job)

    persisted = {
        "body_revision": BODY_REVISION,
        "canonical_body_id": "canonical-body",
        "source_binding": str(source_binding),
        "source_binding_sha256": _file_sha(source_binding),
        "body_review": str(review),
        "body_review_sha256": _file_sha(review),
    }
    monkeypatch.setattr(authority, "_verify_persisted_receipts", lambda **_kwargs: dict(persisted))
    return job_root, source_binding, manifest, job


def _setup_real_persisted_receipts(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, dict]:
    _old_job_root, _old_binding, manifest, job = _setup(tmp_path, monkeypatch)

    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("BODYRIG_DATA_DIR", raising=False)
    monkeypatch.setattr(authority, "_verify_persisted_receipts", _REAL_VERIFY_PERSISTED_RECEIPTS)

    people = local / "BodyRig" / "people"
    source_value = {
        "kind": "stash-performer",
        "performer_id": STASH_PERFORMER_ID,
        "performer_name": "Fixture Person",
        "disambiguation": "",
    }
    profile = {
        "format": "modelrig-person-profile",
        "version": 1,
        "person_id": PERSON_ID,
        "display_name": "Fixture Person",
        "aliases": [],
        "created_utc": "2026-09-09T00:00:00Z",
        "updated_utc": "2026-09-09T00:00:00Z",
        "source": source_value,
        "active_person_revision": None,
        "body_revisions": [
            {
                "revision_id": BODY_REVISION,
                "created_utc": "2026-09-09T00:00:00Z",
                "body_id": "canonical-body",
                "package_sha256": PACKAGE_SHA,
                "package_path": str(local / "BodyRig" / "bodies" / "canonical-body.mrbody"),
                "preview_path": None,
                "feedback": "fixture",
            }
        ],
        "voice_revisions": [],
        "personality_revisions": [],
        "person_revisions": [],
    }
    _write_json(people / f"{PERSON_ID}.json", profile)

    source_binding = people / ".source-bindings" / PERSON_ID / f"{BODY_REVISION}.json"
    media_name = Path(json.loads(manifest.read_text(encoding="utf-8"))["selected"][0]["path"]).name
    _write_json(
        source_binding,
        {
            "format": "bodyrig-person-source-binding",
            "version": 1,
            "person_id": PERSON_ID,
            "source": source_value,
            "component": {
                "kind": "body",
                "revision_id": BODY_REVISION,
                "artifact_sha256": PACKAGE_SHA,
            },
            "evidence": {
                "kind": "stash-physical-source-manifest-v1",
                "sha256": _file_sha(manifest),
                "ref": str(manifest),
                "source_files": [
                    {"scene_id": "scene-1", "name": media_name, "sha256": "9" * 64},
                ],
            },
            "created_utc": "2026-09-09T00:00:00Z",
        },
    )

    review_root = people / ".body-reviews" / PERSON_ID / PACKAGE_SHA
    render_manifest = review_root / "fidelity-render-set.json"
    comparison_authority = review_root / "comparison-authority.json"
    _write_json(render_manifest, {"format": "fixture-render-manifest"})
    _write_json(comparison_authority, {"format": "fixture-comparison-authority"})
    views = []
    for view in ("front-full", "three-quarter-full", "side-full", "face-front"):
        image = review_root / f"{view}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"fixture-{view}".encode("utf-8"))
        views.append(
            {
                "view": view,
                "file": image.name,
                "sha256": _file_sha(image),
                "width": 1024,
                "height": 1024,
            }
        )
    review = review_root / "review.json"
    _write_json(
        review,
        {
            "format": "bodyrig-person-body-review",
            "version": 1,
            "person_id": PERSON_ID,
            "body_id": "canonical-body",
            "package_sha256": PACKAGE_SHA,
            "bodyrig_revision": REVISION,
            "runtime_manifest_sha256": "1" * 64,
            "semantics": "visual-fidelity-not-identity-verification",
            "render_manifest_sha256": _file_sha(render_manifest),
            "comparison_authority_sha256": _file_sha(comparison_authority),
            "views": views,
        },
    )

    job_root = local / "BodyRig" / "ui-jobs" / JOB_ID
    job["source_binding_sha256"] = _file_sha(source_binding)
    job["body_review_sha256"] = _file_sha(review)
    _write_json(job_root / "job.json", job)
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
    assert result["body_revision"] == BODY_REVISION
    assert result["canonical_body_id"] == "canonical-body"
    assert result["package_sha256"] == PACKAGE_SHA
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


def test_receipt_authority_rejects_boolean_job_version(tmp_path: Path, monkeypatch) -> None:
    job_root, _source_binding, _manifest, job = _setup(tmp_path, monkeypatch)
    job["version"] = True
    _write_json(job_root / "job.json", job)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="body job format/version mismatch"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_rejects_boolean_source_enqueue_version(tmp_path: Path, monkeypatch) -> None:
    job_root, _source_binding, _manifest, job = _setup(tmp_path, monkeypatch)
    job["source_enqueue_authority"]["version"] = True
    _write_json(job_root / "job.json", job)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="source enqueue authority format/version mismatch"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_rejects_boolean_source_manifest_version(tmp_path: Path, monkeypatch) -> None:
    job_root, source_binding, manifest, job = _setup_real_persisted_receipts(tmp_path, monkeypatch)
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_value["version"] = True
    _write_json(manifest, manifest_value)

    binding_value = json.loads(source_binding.read_text(encoding="utf-8"))
    binding_value["evidence"]["sha256"] = _file_sha(manifest)
    _write_json(source_binding, binding_value)
    job["source_binding_sha256"] = _file_sha(source_binding)
    _write_json(job_root / "job.json", job)

    with pytest.raises(authority.BodyJobReceiptAuthorityError, match="source manifest format/version mismatch"):
        authority.inspect_succeeded_body_job_receipts(
            job_id=JOB_ID,
            expected_revision=REVISION,
            expected_person_id=PERSON_ID,
        )


def test_receipt_authority_preserves_numeric_float_v1_compatibility(tmp_path: Path, monkeypatch) -> None:
    job_root, source_binding, manifest, job = _setup_real_persisted_receipts(tmp_path, monkeypatch)

    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_value["version"] = 1.0
    _write_json(manifest, manifest_value)

    binding_value = json.loads(source_binding.read_text(encoding="utf-8"))
    binding_value["evidence"]["sha256"] = _file_sha(manifest)
    _write_json(source_binding, binding_value)

    job["version"] = 1.0
    job["source_enqueue_authority"]["version"] = 1.0
    job["source_binding_sha256"] = _file_sha(source_binding)
    _write_json(job_root / "job.json", job)

    result = authority.inspect_succeeded_body_job_receipts(
        job_id=JOB_ID,
        expected_revision=REVISION,
        expected_person_id=PERSON_ID,
    )
    assert result["body_job_id"] == JOB_ID
    assert result["stash_performer_id"] == STASH_PERFORMER_ID
    assert result["source_evidence_sha256"] == _file_sha(manifest)
    assert result["comparison_only"] is True
    assert result["human_visual_authority_required"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
