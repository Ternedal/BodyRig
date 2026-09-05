from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.ui_body_resume as resume
from bodyrig.app import app
from bodyrig.interrupted_fit_recovery import ADOPT_COMPLETE_PACKAGE, RESUME_FIT_ONLY
from bodyrig.ui_jobs import UiJobError


REVISION = "1" * 40


def test_workspace_marker_accepts_only_managed_bodyrig_identity_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(resume.tempfile, "gettempdir", lambda: str(tmp_path))
    workspace = tmp_path / "BodyRig" / "identity-workspaces" / "person-abc-20260903-deadbeef"
    workspace.mkdir(parents=True)
    log = tmp_path / "job.log"
    log.write_text(
        "noise\n"
        f"Private identity workspace: {workspace}\n"
        f"Private identity workspace retained after failed build for recovery: {workspace}\n",
        encoding="utf-8",
    )
    job = {"person_id": "person-abc", "log_path": str(log)}
    assert resume._identity_workspace_from_log(job) == workspace.resolve()

    outside = tmp_path / "other" / "person-abc-deadbeef"
    outside.mkdir(parents=True)
    log.write_text(f"Private identity workspace: {outside}\n", encoding="utf-8")
    with pytest.raises(UiJobError, match="outside BodyRig's managed recovery roots"):
        resume._identity_workspace_from_log(job)


def test_active_job_gate_ignores_source_and_current_resume_but_not_third_job(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [
        {"job_id": "failed-source", "status": "failed"},
        {"job_id": "current-resume", "status": "running"},
        {"job_id": "third-job", "status": "queued"},
    ]
    monkeypatch.setattr(resume.ui_jobs, "list", lambda *, person_id=None: list(jobs))
    active = resume._active_jobs_for_person(
        "person-abc",
        ignore_job_ids={"failed-source", "current-resume"},
    )
    assert [item["job_id"] for item in active] == ["third-job"]

    jobs.pop()
    assert resume._active_jobs_for_person(
        "person-abc",
        ignore_job_ids={"failed-source", "current-resume"},
    ) == []


def test_resume_status_refuses_different_checkout_revision_before_recovery_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "kind": "body-build",
        "status": "failed",
        "person_id": "person-abc",
        "bodyrig_revision": REVISION,
    }
    monkeypatch.setattr(resume, "_job_path", lambda job_id: Path(job_id))
    monkeypatch.setattr(resume, "_read_job", lambda path: dict(source))
    monkeypatch.setattr(resume, "_active_jobs_for_person", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        resume,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": "2" * 40, "root": "fixture", "powershell": "pwsh"},
    )

    called = False

    def unexpected_plan(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("recovery plan must not run across revisions")

    monkeypatch.setattr(resume, "build_recovery_plan", unexpected_plan)
    status = resume.inspect_body_resume("failed-source")
    assert status["available"] is False
    assert "exact BodyRig revision" in status["reason"]
    assert called is False


def _status_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, Path]:
    source = {
        "kind": "body-build",
        "status": "failed",
        "person_id": "person-abc",
        "bodyrig_revision": REVISION,
        "session_report": str(tmp_path / "physical-session.json"),
        "clone_output": str(tmp_path / "clone-output"),
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(resume, "_job_path", lambda job_id: Path(job_id))
    monkeypatch.setattr(resume, "_read_job", lambda path: dict(source))
    monkeypatch.setattr(resume, "_active_jobs_for_person", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        resume,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": REVISION, "root": "fixture", "powershell": "pwsh"},
    )
    monkeypatch.setenv("STASH_URL", "http://stash.invalid:9998")
    monkeypatch.setenv("STASH_API_KEY", "local-fixture-secret")
    monkeypatch.setattr(resume, "_identity_workspace_from_log", lambda job: workspace)
    monkeypatch.setattr(
        resume,
        "load_profile",
        lambda library, person_id: {
            "person_id": person_id,
            "source": {"kind": "stash-performer", "performer_id": "42"},
        },
    )
    return source, workspace


def test_resume_status_exposes_fit_only_recovery_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _source, workspace = _status_fixture(monkeypatch, tmp_path)
    calls: list[dict] = []

    def plan(**kwargs):
        calls.append(kwargs)
        return {
            "bodyrig_revision": REVISION,
            "performer_id": "42",
            "failed_session_id": "session-fixture",
            "recovery_mode": RESUME_FIT_ONLY,
            "package_already_complete": False,
            "package_sha256": None,
            "authority": {"reconstruction_sha256": "a" * 64},
        }

    monkeypatch.setattr(resume, "build_recovery_plan", plan)
    status = resume.inspect_body_resume("failed-source")
    assert status["available"] is True
    assert status["bodyrig_revision"] == REVISION
    assert status["recovery_mode"] == RESUME_FIT_ONLY
    assert status["reconstruction_sha256"] == "a" * 64
    assert status["package_sha256"] is None
    assert status["fitter_rerun"] is True
    assert status["expensive_reconstruction_rerun"] is False
    assert len(calls) == 1
    assert calls[0]["current_revision"] == REVISION
    assert calls[0]["identity_workspace"] == workspace


def test_resume_status_exposes_complete_package_adoption_without_reconstruction_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _status_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        resume,
        "build_recovery_plan",
        lambda **kwargs: {
            "bodyrig_revision": REVISION,
            "performer_id": "42",
            "failed_session_id": "session-fixture",
            "recovery_mode": ADOPT_COMPLETE_PACKAGE,
            "package_already_complete": True,
            "package_sha256": "b" * 64,
            "authority": {"reconstruction_sha256": None},
        },
    )
    status = resume.inspect_body_resume("failed-source")
    assert status["available"] is True
    assert status["recovery_mode"] == ADOPT_COMPLETE_PACKAGE
    assert status["package_sha256"] == "b" * 64
    assert status["reconstruction_sha256"] is None
    assert status["fitter_rerun"] is False
    assert status["expensive_reconstruction_rerun"] is False
    assert "fitter and reconstruction will not rerun" in status["reason"]


def test_resume_status_refuses_inconsistent_mode_package_binding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _status_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        resume,
        "build_recovery_plan",
        lambda **kwargs: {
            "bodyrig_revision": REVISION,
            "performer_id": "42",
            "failed_session_id": "session-fixture",
            "recovery_mode": ADOPT_COMPLETE_PACKAGE,
            "package_already_complete": False,
            "package_sha256": "b" * 64,
            "authority": {"reconstruction_sha256": None},
        },
    )
    status = resume.inspect_body_resume("failed-source")
    assert status["available"] is False
    assert "mode/package binding" in status["reason"]


def test_resume_worker_is_mode_bound_and_verifies_recovery_receipt_before_gate_a() -> None:
    source = Path(resume.__file__).read_text(encoding="utf-8")
    assert "ignore_job_ids={source_job_id, job_id}" in source
    assert "resume-interrupted-physical-fit.ps1" in source
    assert "accept-physical-clone.ps1" in source
    assert "run-fidelity-windows-render-probe.ps1" in source
    assert '"resume_mode": mode' in source
    assert '"resume_of_job_id": job_id' in source
    assert '"resume_reconstruction_sha256"' in source
    assert '"resume_package_sha256"' in source
    assert "_verify_enqueued_mode(job, plan)" in source
    receipt_check = source.index("_verify_recovery_receipt(recovery_receipt_path, mode=mode, plan=plan)")
    gate_a = source.index('str(repo_root / "accept-physical-clone.ps1")')
    assert receipt_check < gate_a
    assert 'value.get("production_activation") is not False' in source
    assert 'value.get("human_visual_authority_required") is not True' in source


def test_resume_api_routes_are_registered_once() -> None:
    resume_status_routes = [
        route
        for route in app.routes
        if route.path == "/api/v1/jobs/{job_id}/resume-status" and "GET" in getattr(route, "methods", set())
    ]
    resume_routes = [
        route
        for route in app.routes
        if route.path == "/api/v1/jobs/{job_id}/resume" and "POST" in getattr(route, "methods", set())
    ]
    assert len(resume_status_routes) == 1
    assert len(resume_routes) == 1


def test_person_studio_surfaces_explicit_recovery_modes_and_reconnects_auto_flow() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
    javascript = (root / "bodyrig" / "ui" / "body_resume.js").read_text(encoding="utf-8")
    assert '<script src="/ui/body_resume.js" defer></script>' in html
    assert "Genoptag fitter fra bevaret reconstruction" in javascript
    assert "Adoptér allerede færdig package" in javascript
    assert "adopt-complete-package" in javascript
    assert "resume-fit-only" in javascript
    assert "/resume-status" in javascript
    assert "body_job_id = resumeJobId" in javascript
    assert 'workflow.state = "body"' in javascript
    assert 'if (workflow.body_job_id !== sourceJobId) return;' in javascript
    assert 'workflow.body_job_id !== sourceJobId && workflow.state !== "failed"' not in javascript
    assert "fitter og reconstruction genkøres ikke" in javascript
    assert "PHALP/4D-Humans reconstruction genkøres ikke" in javascript
