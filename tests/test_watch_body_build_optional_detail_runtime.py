from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-body-build.ps1"
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
REVISION = "3" * 40


def test_missing_checkpoint_detail_does_not_crash_strictmode_monitor(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows path translation is exercised by the production-OS CI job")
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is required")

    data_root = tmp_path / "data"
    local = tmp_path / "local"
    temp_root = tmp_path / "temp"
    job_root = data_root / "ui-jobs" / JOB_ID
    source_parent = tmp_path / PERSON_ID
    checkpoint_root = source_parent / "bodyrig-recovery-checkpoints"
    staging = temp_root / "bodyrig-wsl-recovery-optional-detail"
    for path in (job_root, local, checkpoint_root, staging):
        path.mkdir(parents=True, exist_ok=True)

    source = source_parent / "segment.mp4"
    source.write_bytes(b"fixture")
    drive = source.drive.rstrip(":").lower()
    tail = source.as_posix()[3:] if source.as_posix()[1:3] == ":/" else source.as_posix().lstrip("/")
    wsl_source = f"/mnt/{drive}/{tail}"

    (checkpoint_root / "segment-01.status.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-recovery-segment-status",
                "version": 1,
                "source_index": 0,
                "state": "running",
            }
        ),
        encoding="utf-8",
    )
    (checkpoint_root / "segment-01.log").write_text("Tracking : segment-0 50%\n", encoding="utf-8")
    (staging / "request.json").write_text(json.dumps({"sources": [wsl_source]}), encoding="utf-8")
    (staging / "stderr.log").write_text("", encoding="utf-8")

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "running",
        "created_utc": "2026-09-10T10:00:00Z",
        "started_utc": "2026-09-10T10:00:01Z",
        "completed_utc": None,
        "bodyrig_revision": REVISION,
        "clone_output": str(job_root / "clone-output"),
        "acceptance_dir": str(job_root / "acceptance"),
        "fidelity_dir": str(job_root / "fidelity-review"),
        "log_path": str(job_root / "missing.log"),
    }
    (job_root / "job.json").write_text(json.dumps(job), encoding="utf-8")

    env = os.environ.copy()
    env["BODYRIG_DATA_DIR"] = str(data_root)
    env["LOCALAPPDATA"] = str(local)
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)

    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(SCRIPT), "-JobId", JOB_ID, "-Once", "-NoClear"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Recovery: segment 1/1" in result.stdout
    assert "state: running" in result.stdout
