from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_preview_list_cli as preview_list


def _job(
    root: Path,
    job_id: str,
    *,
    created: str,
    status: str = "succeeded",
    format_value: str = preview_list.FORMAT,
    version_value: object = preview_list.VERSION,
    person_id: str | None = None,
    body_job_id: str = "",
) -> None:
    path = root / job_id / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "format": format_value,
                "version": version_value,
                "job_id": job_id,
                "display_name": f"Person {job_id[-1]}",
                "person_id": person_id if person_id is not None else f"person-{job_id[-1]}",
                "body_job_id": body_job_id,
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


def test_boolean_v1_is_rejected_but_numeric_v1_is_preserved(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / ".high-fidelity-previews"
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    boolean = "hfpreview-" + "9" * 32
    numeric = "hfpreview-" + "a" * 32
    _job(store, boolean, created="2026-09-05T10:00:00Z", version_value=True)
    _job(store, numeric, created="2026-09-05T09:00:00Z", version_value=1.0)

    rows = preview_list.list_recent_previews(limit=10)

    assert [row["job_id"] for row in rows] == [numeric]


def test_scope_filters_before_limit_and_exposes_body_job(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / ".high-fidelity-previews"
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    target_person = "person-" + "a" * 32
    other_person = "person-" + "b" * 32
    target_body_job = "job-" + "c" * 32
    other_body_job = "job-" + "d" * 32
    target = "hfpreview-" + "8" * 32

    _job(
        store,
        target,
        created="2026-09-01T00:00:00Z",
        person_id=target_person,
        body_job_id=target_body_job,
    )
    for index in range(12):
        job_id = "hfpreview-" + f"{index + 20:032x}"
        _job(
            store,
            job_id,
            created=f"2026-09-{12 - index:02d}T00:00:00Z",
            person_id=other_person,
            body_job_id=other_body_job,
        )

    rows = preview_list.list_recent_previews(
        limit=10,
        succeeded_only=True,
        person_id=target_person,
        body_job_id=target_body_job,
    )

    assert [row["job_id"] for row in rows] == [target]
    assert rows[0]["person_id"] == target_person
    assert rows[0]["body_job_id"] == target_body_job


def test_invalid_scope_filter_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(preview_list, "ui_jobs_dir", lambda: tmp_path)
    with pytest.raises(preview_list.HighFidelityPreviewListError, match="person id filter is invalid"):
        preview_list.list_recent_previews(person_id="person-not-canonical")
    with pytest.raises(preview_list.HighFidelityPreviewListError, match="body job id filter is invalid"):
        preview_list.list_recent_previews(body_job_id="job-not-canonical")


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
