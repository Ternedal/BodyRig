from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-body-build.ps1"

JOB_ID = "job-" + ("1" * 32)
PERSON_ID = "person-" + ("2" * 32)
MAIN_REVISION = "3" * 40
PBR_REVISION = "4" * 40
THROUGHPUT_REVISION = "5" * 40
CONTRACT_SHA256 = "6" * 64


def _pwsh() -> str:
    command = shutil.which("pwsh")
    if command is None:
        pytest.skip("pwsh is required for watch-body-build runtime routing tests")
    return command


def _write_fixture(tmp_path: Path, *, plan_revision: str = MAIN_REVISION) -> tuple[dict[str, str], Path]:
    data_root = tmp_path / "data"
    local_app_data = tmp_path / "local"
    job_root = data_root / "ui-jobs" / JOB_ID
    plan_root = local_app_data / "BodyRig" / "ab-baseline-plans"
    job_root.mkdir(parents=True)
    plan_root.mkdir(parents=True)

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "succeeded",
        "created_utc": "2026-09-09T04:00:00Z",
        "started_utc": "2026-09-09T04:01:00Z",
        "completed_utc": "2026-09-09T04:02:00Z",
        "pid": None,
        "bodyrig_revision": MAIN_REVISION,
        "session_report": str(job_root / "physical-session.json"),
        "clone_output": str(job_root / "clone-output"),
        "acceptance_dir": str(job_root / "acceptance"),
        "fidelity_dir": str(job_root / "fidelity-review"),
        # Deliberately leave this path absent. The monitor promises to tolerate
        # an unavailable job log and still route terminal A/B evidence safely.
        "log_path": str(tmp_path / "missing-job.log"),
        "adjustment_request": None,
    }
    (job_root / "job.json").write_text(json.dumps(job), encoding="utf-8")

    plan = {
        "format": "bodyrig-dual-candidate-ab-baseline-plan",
        "version": 1,
        "baseline_job_id": JOB_ID,
        "person_id": PERSON_ID,
        "baseline_bodyrig_revision": plan_revision,
        "candidate_contract_sha256": CONTRACT_SHA256,
        "pbr_candidate": {
            "ref": "candidate/skin-pbr-v2-current-main-20260908",
            "revision": PBR_REVISION,
            "retained_reconstruction_reuse": True,
        },
        "throughput_candidate": {
            "ref": "candidate/recovery-throughput-v3-current-main-20260908",
            "revision": THROUGHPUT_REVISION,
            "separate_candidate_body_build_required": True,
        },
        "ab_baseline_retention": {
            "format": "bodyrig-ab-baseline-retention",
            "version": 1,
            "retain_private_workspace": True,
            "expected_bodyrig_revision": plan_revision,
            "job_id": JOB_ID,
        },
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    plan_path = plan_root / f"{JOB_ID}.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    env = os.environ.copy()
    env["BODYRIG_DATA_DIR"] = str(data_root)
    env["LOCALAPPDATA"] = str(local_app_data)
    return env, plan_path


def _run_monitor(tmp_path: Path, *, plan_revision: str = MAIN_REVISION) -> subprocess.CompletedProcess[str]:
    env, _ = _write_fixture(tmp_path, plan_revision=plan_revision)
    return subprocess.run(
        [
            _pwsh(),
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-JobId",
            JOB_ID,
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


def test_matching_succeeded_baseline_emits_plan_bound_pbr_command(tmp_path: Path) -> None:
    result = _run_monitor(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "=== A/B BASELINE CONTINUATION ===" in result.stdout
    assert "This monitor grants no authority" in result.stdout
    assert "downstream wrapper revalidates" in result.stdout
    assert (
        f".\\run-pbr-ab-from-body-job-plan-bound.ps1 -BaselineJobId '{JOB_ID}'"
        in result.stdout
    )


def test_revision_mismatched_plan_fails_closed_without_next_command(tmp_path: Path) -> None:
    result = _run_monitor(tmp_path, plan_revision="9" * 40)
    assert result.returncode == 0, result.stderr
    assert "=== A/B BASELINE CONTINUATION BLOCKED ===" in result.stdout
    assert "does not structurally match this exact job/revision" in result.stdout
    assert "Next command (downstream revalidates full authority):" not in result.stdout
    assert ".\\run-pbr-ab-from-body-job-plan-bound.ps1" not in result.stdout
