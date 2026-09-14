from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_preview_jobs as preview_jobs


REVISION = "a" * 40
BODY_ID = "performer-42"
CANDIDATE_SHA = "b" * 64


def write_job(root: Path, job_id: str, *, candidate_sha: str = CANDIDATE_SHA) -> None:
    path = root / job_id / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "format": preview_jobs.FORMAT,
        "version": 1,
        "job_id": job_id,
        "status": "succeeded",
        "canonical_body_id": BODY_ID,
        "bodyrig_revision": REVISION,
        "candidate_package_sha256": candidate_sha,
    }), encoding="utf-8")


def configure(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(preview_jobs, "_store_root", lambda: root)
    monkeypatch.setattr(preview_jobs, "_public", lambda job: dict(job))


def test_resolve_succeeded_candidate_requires_one_exact_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    write_job(tmp_path, "hfpreview-" + "1" * 32)
    write_job(tmp_path, "hfpreview-" + "2" * 32, candidate_sha="c" * 64)

    result = preview_jobs.manager.resolve_succeeded_candidate(
        canonical_body_id=BODY_ID,
        bodyrig_revision=REVISION,
        candidate_package_sha256=CANDIDATE_SHA,
    )

    assert result["job_id"] == "hfpreview-" + "1" * 32


def test_resolve_succeeded_candidate_fails_closed_on_zero_or_ambiguous_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path)
    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="no succeeded"):
        preview_jobs.manager.resolve_succeeded_candidate(
            canonical_body_id=BODY_ID,
            bodyrig_revision=REVISION,
            candidate_package_sha256=CANDIDATE_SHA,
        )

    write_job(tmp_path, "hfpreview-" + "1" * 32)
    write_job(tmp_path, "hfpreview-" + "2" * 32)
    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="multiple succeeded"):
        preview_jobs.manager.resolve_succeeded_candidate(
            canonical_body_id=BODY_ID,
            bodyrig_revision=REVISION,
            candidate_package_sha256=CANDIDATE_SHA,
        )


def test_resolve_succeeded_candidate_rejects_invalid_matching_lineage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(preview_jobs, "_store_root", lambda: tmp_path)
    write_job(tmp_path, "hfpreview-" + "1" * 32)

    def invalid(_job: dict) -> dict:
        raise preview_jobs.HighFidelityPreviewError("tampered")

    monkeypatch.setattr(preview_jobs, "_public", invalid)
    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="matching succeeded.*invalid"):
        preview_jobs.manager.resolve_succeeded_candidate(
            canonical_body_id=BODY_ID,
            bodyrig_revision=REVISION,
            candidate_package_sha256=CANDIDATE_SHA,
        )
