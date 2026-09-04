from __future__ import annotations

from pathlib import Path

from bodyrig.ui_jobs import _body_job_view


def _job(tmp_path: Path, *, status: str = "running") -> dict:
    root = tmp_path / "job"
    return {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": "job-0123456789abcdef0123456789abcdef",
        "kind": "body-build",
        "person_id": "person-0123456789abcdef0123456789abcdef",
        "status": status,
        "created_utc": "2026-09-02T18:00:00Z",
        "started_utc": "2026-09-02T18:00:00Z",
        "completed_utc": "2026-09-02T18:10:00Z" if status != "running" else None,
        "log_path": str(root / "job.log"),
        "clone_output": str(root / "clone-output"),
        "acceptance_dir": str(root / "acceptance"),
        "fidelity_dir": str(root / "fidelity-review"),
        "error": None,
    }


def test_body_progress_moves_only_on_pipeline_evidence(tmp_path: Path) -> None:
    job = _job(tmp_path)
    log = Path(job["log_path"])
    log.parent.mkdir(parents=True)
    log.write_text(
        "BodyRig rig readiness: READY\n"
        "Live readiness: PASS\n"
        "Starting Stash clone pipeline.\n",
        encoding="utf-8",
    )

    view = _body_job_view(job)
    assert view["progress"] == 10
    assert view["stage"] == "source_selection"
    assert view["progress_kind"] == "pipeline-phase-estimate-v1"

    clone = Path(job["clone_output"])
    clone.mkdir(parents=True)
    (clone / "bodyrig-stash-source-manifest.json").write_text("{}", encoding="utf-8")
    view = _body_job_view(job)
    assert view["progress"] == 18
    assert view["stage"] == "sources_selected"

    (clone / "bodyrig-observation-evidence.json").write_text("{}", encoding="utf-8")
    view = _body_job_view(job)
    assert view["progress"] == 32
    assert view["stage"] == "high_fidelity_reconstruction"
    assert "længste fase" in view["message"]


def test_body_progress_advances_through_gate_a_and_fidelity(tmp_path: Path) -> None:
    job = _job(tmp_path)
    log = Path(job["log_path"])
    log.parent.mkdir(parents=True)
    log.write_text("BodyRig Stash clone: PASS\n", encoding="utf-8")

    assert _body_job_view(job)["progress"] == 70

    acceptance = Path(job["acceptance_dir"])
    acceptance.mkdir(parents=True)
    assert _body_job_view(job)["progress"] == 78

    (acceptance / "bodyrig-acceptance.json").write_text("{}", encoding="utf-8")
    assert _body_job_view(job)["progress"] == 85

    fidelity = Path(job["fidelity_dir"])
    fidelity.mkdir(parents=True)
    assert _body_job_view(job)["progress"] == 90

    (fidelity / "review.json").write_text("{}", encoding="utf-8")
    view = _body_job_view(job)
    assert view["progress"] == 96
    assert view["stage"] == "registering"


def test_failed_body_job_exposes_bounded_diagnostic_tail(tmp_path: Path) -> None:
    job = _job(tmp_path, status="failed")
    job["error"] = "physical Stash clone failed with exit code 1"
    log = Path(job["log_path"])
    log.parent.mkdir(parents=True)
    log.write_text(
        "BodyRig rig readiness: READY\n"
        "Starting Stash clone pipeline.\n"
        "BodyRig Stash source: performer '42' has no rankable local video sources\n"
        "Stash performer source selection failed with exit code 1\n",
        encoding="utf-8",
    )

    view = _body_job_view(job)
    assert view["progress"] == 10
    assert view["diagnostic_tail"] is not None
    assert "no rankable local video sources" in view["diagnostic_tail"]
    assert len(view["diagnostic_tail"]) <= 4000


def test_completed_body_job_is_exactly_100_percent(tmp_path: Path) -> None:
    view = _body_job_view(_job(tmp_path, status="succeeded"))
    assert view["progress"] == 100
    assert view["stage"] == "complete"
    assert view["diagnostic_tail"] is None
