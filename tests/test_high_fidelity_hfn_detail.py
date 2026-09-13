from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.high_fidelity_continuation_status as continuation
import bodyrig.high_fidelity_hfn_detail as subject


JOB_ID = "hfpreview-" + "a" * 32
PERSON_ID = "person-" + "b" * 32
BODY_REVISION = "body-r0007"
BODY_ID = "body-" + "c" * 32
CAPTURE_ID = "hfncap-" + "d" * 32
REVISION = "e" * 40
SHA = "f" * 64


def _context() -> dict[str, str]:
    return {
        "preview_job_id": JOB_ID,
        "body_job_id": "job-source",
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
    }


def test_hfn_continuation_authority_keeps_review_and_physical_boundaries() -> None:
    assert subject.FORMAT == "bodyrig-high-fidelity-hands-feet-nails-detail"
    assert subject.VERSION == 1
    assert subject.POLICY_REVISION == "bodyrig-high-fidelity-hands-feet-nails-detail-v1"
    assert {
        "source_grounded",
        "geometry_modified",
        "texture_modified",
        "human_review_required",
        "physical_acceptance_required",
        "production_activation",
    } <= subject.TOP_FIELDS


def test_authority_path_stays_inside_exact_preview_continuation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subject, "ui_jobs_dir", lambda: tmp_path)

    path = subject._authority_path(JOB_ID)

    assert path == (
        tmp_path
        / ".high-fidelity-previews"
        / JOB_ID
        / "continuation"
        / "hands-feet-nails-detail"
        / "authority.json"
    ).resolve()
    path.relative_to(tmp_path.resolve())


def test_source_context_requires_same_succeeded_body_lineage(monkeypatch) -> None:
    monkeypatch.setattr(
        subject.preview_manager,
        "get",
        lambda _job: {
            "status": "succeeded",
            "body_job_id": "job-source",
            "canonical_body_id": BODY_ID,
        },
    )
    monkeypatch.setattr(
        subject.ui_jobs,
        "get",
        lambda _job: {
            "kind": "body-build",
            "status": "succeeded",
            "person_id": PERSON_ID,
            "body_revision": BODY_REVISION,
            "canonical_body_id": BODY_ID,
        },
    )

    assert subject._source_context(JOB_ID) == _context()

    monkeypatch.setattr(
        subject.preview_manager,
        "get",
        lambda _job: {
            "status": "succeeded",
            "body_job_id": "job-source",
            "canonical_body_id": "body-other",
        },
    )
    with pytest.raises(subject.HighFidelityHfnDetailError, match="body ids differ"):
        subject._source_context(JOB_ID)


def test_read_hfn_detail_rejects_boolean_version_before_trusting_authority(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"source-package")
    authority = tmp_path / "authority.json"
    authority.write_text(
        json.dumps(
            {
                **{field: "x" for field in subject.TOP_FIELDS},
                "format": subject.FORMAT,
                "version": True,
                "policy_revision": subject.POLICY_REVISION,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "_source_context", lambda _job: _context())
    monkeypatch.setattr(subject, "_authority_path", lambda _job: authority)
    monkeypatch.setattr(
        subject,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": BODY_ID}),
    )

    with pytest.raises(subject.HighFidelityHfnDetailError, match="format/version/policy"):
        subject.read_hfn_detail(JOB_ID, source_package_path=package)


def test_partial_candidate_package_receipt_pair_fails_closed(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "candidate.mrbody"
    receipt = tmp_path / "candidate.json"
    package.write_bytes(b"candidate")
    monkeypatch.setattr(subject, "candidate_paths", lambda *_args, **_kwargs: (package, receipt))

    with pytest.raises(subject.HighFidelityHfnDetailError, match="incomplete"):
        subject._read_candidate(
            tmp_path,
            context=_context(),
            capture_id=CAPTURE_ID,
            candidate_id="hfncand-" + "1" * 32,
        )


def test_prepare_refuses_to_run_before_final_hfn_gate(monkeypatch, tmp_path: Path) -> None:
    landmark = tmp_path / "landmarks.json"
    landmark.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "_source_context", lambda _job: _context())
    monkeypatch.setattr(
        continuation,
        "inspect_continuation",
        lambda _job: {
            "next_gate": {"gate": "face_secondary_promotion"},
            "current_package_path": str(tmp_path / "face.mrbody"),
            "current_package_sha256": SHA,
        },
    )

    with pytest.raises(subject.HighFidelityHfnDetailError, match="final continuation gate"):
        subject.prepare_hfn_detail(
            JOB_ID,
            capture_id=CAPTURE_ID,
            landmark_evidence_path=landmark,
            bodyrig_revision=REVISION,
        )
