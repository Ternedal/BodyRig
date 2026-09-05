from __future__ import annotations

import json
from pathlib import Path

import bodyrig.high_fidelity_preview_list_cli as preview_list


def _job(root: Path, job_id: str, *, created: str, status: str = "succeeded", format_value: str = preview_list.FORMAT) -> None:
    path = root / job_id / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "format": format_value,
                "version": preview_list.VERSION,
                "job_id": job_id,
                "display_name": f"Person {job_id[-1]}",
                "person_id": f"person-{job_id[-1]}",
                "body_revision": "body-r1",
                "canonical_body_id": "bodyid-123",
                "target_family": "neutral",
                "status": status,
                "stage": "review-ready" if status == "succeeded" else "failed",
                "bodyrig_revision": "c" * 40,
                "created_utc": created,
                "completed_utc": created,
            }
        ),
        encoding="utf-8",
    )


def test_lists_recent_valid_jobs_without_mutation(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / ".high-fidelity-previews"
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    first = "hfpreview-" + "1" * 32
    second = "hfpreview-" + "2" * 32
    _job(store, first, created="2026-09-05T08:00:00Z")
    _job(store, second, created="2026-09-05T09:00:00Z")

    before = {path: path.read_bytes() for path in store.glob("*/job.json")}
    rows = preview_list.list_recent_previews(limit=10)
    after = {path: path.read_bytes() for path in store.glob("*/job.json")}

    assert [row["job_id"] for row in rows] == [second, first]
    assert before == after


def test_succeeded_only_filters_failed_and_invalid_records(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / ".high-fidelity-previews"
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    succeeded = "hfpreview-" + "3" * 32
    failed = "hfpreview-" + "4" * 32
    invalid = "hfpreview-" + "5" * 32
    _job(store, succeeded, created="2026-09-05T09:00:00Z")
    _job(store, failed, created="2026-09-05T10:00:00Z", status="failed")
    _job(store, invalid, created="2026-09-05T11:00:00Z", format_value="wrong-format")

    rows = preview_list.list_recent_previews(limit=10, succeeded_only=True)

    assert [row["job_id"] for row in rows] == [succeeded]


def test_job_id_must_match_its_persisted_directory(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / ".high-fidelity-previews"
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    path = store / ("hfpreview-" + "6" * 32) / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"format": preview_list.FORMAT, "version": 1, "job_id": "hfpreview-" + "7" * 32}),
        encoding="utf-8",
    )

    assert preview_list.list_recent_previews(limit=10) == []
