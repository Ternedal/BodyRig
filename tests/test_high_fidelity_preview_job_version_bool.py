from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_preview_jobs as preview_jobs


JOB_ID = "hfpreview-" + "d" * 32


def _write_job(tmp_path: Path, *, version: object) -> Path:
    root = tmp_path / preview_jobs.ROOT_DIRNAME / JOB_ID
    root.mkdir(parents=True)
    path = root / "job.json"
    path.write_text(
        json.dumps(
            {
                "format": preview_jobs.FORMAT,
                "version": version,
                "job_id": JOB_ID,
                "status": "failed",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_preview_job_rejects_boolean_v1(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(preview_jobs, "ui_jobs_dir", lambda: tmp_path)
    path = _write_job(tmp_path, version=True)

    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="unsupported high-fidelity preview job"):
        preview_jobs._read_job(path)


def test_preview_job_preserves_numeric_v1_compatibility(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(preview_jobs, "ui_jobs_dir", lambda: tmp_path)
    path = _write_job(tmp_path, version=1.0)

    value = preview_jobs._read_job(path)

    assert value["job_id"] == JOB_ID
    assert value["version"] == 1.0


def test_completed_preview_nested_v1_boundaries_use_strict_helper() -> None:
    source = inspect.getsource(preview_jobs._validate_completed)

    assert 'not _is_v1(summary.get("version"))' in source
    assert 'not _is_v1(component.get("version"))' in source
    assert 'not _is_v1(runtime_value.get("version"))' in source
    assert preview_jobs._is_v1(True) is False
    assert preview_jobs._is_v1(1.0) is True
