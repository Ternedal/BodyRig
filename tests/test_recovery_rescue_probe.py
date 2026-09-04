from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bodyrig.bridges.hmr2_checkpoint_bridge import CHECKPOINT_VERSION, RAW_META_FORMAT
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from bodyrig.recovery_rescue_probe import FORMAT, VERSION, inspect_job


JOB_ID = "job-" + "a" * 32
PERSON_ID = "person-7e9819fbed344ecc9cf58b0875932a44"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _job(root: Path, *, now: datetime) -> Path:
    job_root = root / "ui-jobs" / JOB_ID
    log_path = job_root / "job.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("BodyRig recovery preflight: OK\nterminal recovery detail\n", encoding="utf-8")
    _write_json(
        job_root / "job.json",
        {
            "format": "bodyrig-ui-job",
            "version": 1,
            "job_id": JOB_ID,
            "kind": "body-build",
            "person_id": PERSON_ID,
            "status": "failed",
            "started_utc": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "completed_utc": (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "bodyrig_revision": "0" * 40,
            "log_path": str(log_path),
            "error": "physical Stash clone failed with exit code 1",
        },
    )
    return job_root


def test_probe_counts_surviving_exact_revision_raw_checkpoints(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    data = tmp_path / "data"
    temp = tmp_path / "temp"
    temp.mkdir()
    _job(data, now=now)

    stamp = now.strftime("%Y%m%d-%H%M%S")
    checkpoint_root = (
        data
        / "observation-workspaces"
        / f"{PERSON_ID}-{stamp}-{'b' * 32}"
        / "selected-segments"
        / "bodyrig-recovery-checkpoints"
    )
    raw = checkpoint_root / "segment-01.phalp.pkl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"raw PHALP evidence")
    _write_json(
        checkpoint_root / "segment-01.phalp.json",
        {
            "format": RAW_META_FORMAT,
            "version": CHECKPOINT_VERSION,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "source_index": 0,
            "source_sha256": "c" * 64,
        },
    )
    _write_json(
        checkpoint_root / "segment-01.status.json",
        {"state": "complete"},
    )

    report = inspect_job(JOB_ID, data_root=data, temp_root=temp)

    assert report["format"] == FORMAT
    assert report["version"] == VERSION
    assert report["read_only"] is True
    assert report["reusable_raw_checkpoints"] == 1
    assert report["legacy_recovery_survived"] is True
    assert report["checkpoint_workspaces"][0]["segments"][0]["raw_checkpoint"] is True
    assert report["checkpoint_workspaces"][0]["segments"][0]["state"] == "complete"


def test_probe_rejects_wrong_revision_checkpoint(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    data = tmp_path / "data"
    temp = tmp_path / "temp"
    temp.mkdir()
    _job(data, now=now)

    stamp = now.strftime("%Y%m%d-%H%M%S")
    checkpoint_root = (
        data
        / "observation-workspaces"
        / f"{PERSON_ID}-{stamp}-{'d' * 32}"
        / "selected-segments"
        / "bodyrig-recovery-checkpoints"
    )
    raw = checkpoint_root / "segment-01.phalp.pkl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"raw PHALP evidence")
    _write_json(
        checkpoint_root / "segment-01.phalp.json",
        {
            "format": RAW_META_FORMAT,
            "version": CHECKPOINT_VERSION,
            "adapter": ADAPTER_NAME,
            "revision": "wrong-revision",
            "source_index": 0,
            "source_sha256": "e" * 64,
        },
    )

    report = inspect_job(JOB_ID, data_root=data, temp_root=temp)
    assert report["reusable_raw_checkpoints"] == 0
    assert report["checkpoint_workspaces"][0]["segments"][0]["raw_checkpoint"] is False


def test_probe_surfaces_retained_wsl_staging_diagnostic(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    data = tmp_path / "data"
    temp = tmp_path / "temp"
    temp.mkdir()
    _job(data, now=now)

    staging = temp / "bodyrig-wsl-recovery-deadbeef"
    staging.mkdir()
    _write_json(
        staging / "status.json",
        {"format": "bodyrig-file-command-status", "version": 1, "returncode": 1},
    )
    (staging / "stderr.log").write_text("earlier line\nprecise WSL terminal failure\n", encoding="utf-8")
    (staging / "result.json").write_bytes(b"")

    report = inspect_job(JOB_ID, data_root=data, temp_root=temp)
    assert len(report["wsl_staging_candidates"]) == 1
    candidate = report["wsl_staging_candidates"][0]
    assert candidate["status"]["returncode"] == 1
    assert "precise WSL terminal failure" in candidate["stderr_tail"]
    assert report["legacy_recovery_survived"] is True


def test_probe_does_not_mutate_evidence(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    data = tmp_path / "data"
    temp = tmp_path / "temp"
    temp.mkdir()
    _job(data, now=now)

    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    inspect_job(JOB_ID, data_root=data, temp_root=temp)
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
