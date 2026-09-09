from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-throughput-candidate-from-ab-plan.ps1"

BASELINE_JOB_ID = "job-" + ("1" * 32)
CANDIDATE_JOB_ID = "job-" + ("7" * 32)
PERSON_ID = "person-" + ("2" * 32)
STASH_PERFORMER_ID = "stash-performer-fixture"
MAIN_REVISION = "3" * 40
PBR_REVISION = "4" * 40
THROUGHPUT_REVISION = "5" * 40
CONTRACT_SHA256 = "6" * 64
BASELINE_PLAN_SHA256 = "8" * 64
BASELINE_JOB_SHA256 = "9" * 64
PBR_AUTHORITY_SHA256 = "a" * 64
PBR_REVIEW_SHA256 = "b" * 64
PBR_FINGERPRINT_SHA256 = "c" * 64


def _pwsh() -> str:
    command = shutil.which("pwsh")
    if command is None:
        pytest.skip("pwsh is required for throughput candidate watcher runtime tests")
    return command


def _write_fixture(
    tmp_path: Path,
    *,
    status: str = "succeeded",
    gate_performer_id: str = STASH_PERFORMER_ID,
) -> dict[str, str]:
    data_root = tmp_path / "data"
    local_app_data = tmp_path / "local"
    job_root = data_root / "ui-jobs" / CANDIDATE_JOB_ID
    plan_root = local_app_data / "BodyRig" / "ab-baseline-plans"
    job_root.mkdir(parents=True)
    plan_root.mkdir(parents=True)

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": CANDIDATE_JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": status,
        "created_utc": "2026-09-09T18:00:00Z",
        "started_utc": "2026-09-09T18:01:00Z",
        "completed_utc": "2026-09-09T18:02:00Z",
        "pid": None,
        "bodyrig_revision": THROUGHPUT_REVISION,
        "session_report": str(job_root / "physical-session.json"),
        "clone_output": str(job_root / "clone-output"),
        "acceptance_dir": str(job_root / "acceptance"),
        "fidelity_dir": str(job_root / "fidelity-review"),
        "log_path": str(tmp_path / "missing-job.log"),
        "adjustment_request": None,
        "source_enqueue_authority": {
            "format": "bodyrig-body-build-source-enqueue-authority",
            "version": 1,
            "job_id": CANDIDATE_JOB_ID,
            "person_id": PERSON_ID,
            "stash_performer_id": STASH_PERFORMER_ID,
            "expected_bodyrig_revision": THROUGHPUT_REVISION,
        },
    }
    (job_root / "job.json").write_text(json.dumps(job), encoding="utf-8")

    run_plan = {
        "format": "bodyrig-throughput-candidate-run-plan",
        "version": 1,
        "baseline_plan_sha256": BASELINE_PLAN_SHA256,
        "candidate_contract_sha256": CONTRACT_SHA256,
        "baseline_job_id": BASELINE_JOB_ID,
        "baseline_job_json_sha256": BASELINE_JOB_SHA256,
        "baseline_bodyrig_revision": MAIN_REVISION,
        "person_id": PERSON_ID,
        "throughput_candidate_ref": "candidate/recovery-throughput-v3-current-main-20260908",
        "throughput_candidate_revision": THROUGHPUT_REVISION,
        "candidate_job_id": CANDIDATE_JOB_ID,
        "candidate_workspace_retained": False,
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    run_plan_path = plan_root / f"{BASELINE_JOB_ID}-throughput-{CANDIDATE_JOB_ID}.json"
    run_plan_path.write_text(json.dumps(run_plan), encoding="utf-8")
    run_plan_sha256 = hashlib.sha256(run_plan_path.read_bytes()).hexdigest()

    gate = {
        "format": "bodyrig-throughput-pbr-human-review-gate",
        "version": 1,
        "baseline_job_id": BASELINE_JOB_ID,
        "candidate_job_id": CANDIDATE_JOB_ID,
        "person_id": PERSON_ID,
        "stash_performer_id": gate_performer_id,
        "baseline_plan_sha256": BASELINE_PLAN_SHA256,
        "candidate_run_plan_sha256": run_plan_sha256,
        "candidate_contract_sha256": CONTRACT_SHA256,
        "baseline_revision": MAIN_REVISION,
        "pbr_candidate_ref": "candidate/skin-pbr-v3-linear-light-20260909",
        "pbr_candidate_revision": PBR_REVISION,
        "throughput_candidate_ref": run_plan["throughput_candidate_ref"],
        "throughput_candidate_revision": THROUGHPUT_REVISION,
        "pbr_run_dir": str(tmp_path / "pbr-run"),
        "pbr_human_review_authority_sha256": PBR_AUTHORITY_SHA256,
        "pbr_human_review_sha256": PBR_REVIEW_SHA256,
        "pbr_decision": "right",
        "pbr_stable_evidence_fingerprint_sha256": PBR_FINGERPRINT_SHA256,
        "comparison_only": True,
        "human_visual_authority_recorded": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    gate_path = plan_root / f"{BASELINE_JOB_ID}-throughput-{CANDIDATE_JOB_ID}-pbr-gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    env = os.environ.copy()
    env["BODYRIG_DATA_DIR"] = str(data_root)
    env["LOCALAPPDATA"] = str(local_app_data)
    return env


def _run(tmp_path: Path, **fixture_kwargs: str) -> subprocess.CompletedProcess[str]:
    env = _write_fixture(tmp_path, **fixture_kwargs)
    return subprocess.run(
        [
            _pwsh(),
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-BaselineJobId",
            BASELINE_JOB_ID,
            "-CandidateJobId",
            CANDIDATE_JOB_ID,
            "-Once",
            "-NoClear",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_succeeded_candidate_emits_canonical_plan_bound_continuation(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "=== THROUGHPUT CANDIDATE CONTINUATION ===" in result.stdout
    assert "This watcher grants no authority" in result.stdout
    assert "downstream revalidates full authority" in result.stdout
    assert (
        f".\\continue-throughput-review-from-ab-plan.ps1 -BaselineJobId '{BASELINE_JOB_ID}' "
        f"-CandidateJobId '{CANDIDATE_JOB_ID}'"
    ) in result.stdout


def test_gate_performer_drift_fails_closed_without_next_command(tmp_path: Path) -> None:
    result = _run(tmp_path, gate_performer_id="different-performer")
    assert result.returncode == 0, result.stderr
    assert "=== THROUGHPUT CANDIDATE CONTINUATION BLOCKED ===" in result.stdout
    assert "does not structurally match the exact candidate run plan/job/source" in result.stdout
    assert "Next command (downstream revalidates full authority):" not in result.stdout


def test_non_succeeded_candidate_never_emits_continuation(tmp_path: Path) -> None:
    result = _run(tmp_path, status="failed")
    assert result.returncode == 0, result.stderr
    assert "=== THROUGHPUT CANDIDATE CONTINUATION BLOCKED ===" in result.stdout
    assert "Continuation requires the candidate job to succeed normally" in result.stdout
    assert "Next command (downstream revalidates full authority):" not in result.stdout
