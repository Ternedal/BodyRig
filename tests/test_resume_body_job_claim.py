from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.resume_body_job as resume_module
from bodyrig.resume_body_job import ResumeBodyJobError


JOB_ID = "job-" + "a" * 32


def test_gate_a_resume_claim_is_create_only_and_exclusive(tmp_path: Path, monkeypatch) -> None:
    job_path = tmp_path / JOB_ID / "job.json"
    job_path.parent.mkdir(parents=True)
    job_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(resume_module, "_job_path", lambda _job_id: job_path)

    claim = resume_module._acquire_resume_claim(JOB_ID)
    assert claim.is_file()
    with pytest.raises(ResumeBodyJobError, match="already claimed"):
        resume_module._acquire_resume_claim(JOB_ID)

    resume_module._release_resume_claim(claim)
    assert not claim.exists()

    replacement = resume_module._acquire_resume_claim(JOB_ID)
    assert replacement.is_file()
    resume_module._release_resume_claim(replacement)


def test_resume_context_keeps_original_gate_a_failure_authority_for_retry(tmp_path: Path, monkeypatch) -> None:
    job_path = tmp_path / JOB_ID / "job.json"
    job = {
        "kind": "body-build",
        "status": "failed",
        "error": "later Gate A resume attempt failed transiently",
        "resume_source_error": "high-fidelity Gate A failed with exit code 1",
        "bodyrig_revision": "a" * 40,
        "acceptance_dir": str(tmp_path / "acceptance"),
        "fidelity_dir": str(tmp_path / "fidelity"),
        "session_report": str(tmp_path / "session.json"),
    }
    monkeypatch.setattr(resume_module, "_job_path", lambda _job_id: job_path)
    monkeypatch.setattr(resume_module, "_read_job", lambda _path: dict(job))
    monkeypatch.setattr(
        resume_module,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": "b" * 40},
    )

    context = resume_module._resume_context(JOB_ID)
    assert context["producer_revision"] == "a" * 40
    assert context["validator_revision"] == "b" * 40
