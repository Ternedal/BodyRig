from __future__ import annotations

import pytest

import bodyrig.revision_bound_body_build as revision_bound


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32


class TrackingLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self):
        assert self.held is False
        self.held = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.held = False


class FakeManager:
    def __init__(self, job_revision: str) -> None:
        self._lock = TrackingLock()
        self.job_revision = job_revision
        self.started = 0
        self.cancelled: list[str] = []

    def start_body_build(self, person_id: str, *, feedback: str, changes) -> dict:
        assert self._lock.held is True
        assert feedback == ""
        assert changes is None
        self.started += 1
        return {
            "job_id": JOB_ID,
            "kind": "body-build",
            "person_id": person_id,
            "status": "queued",
            "bodyrig_revision": self.job_revision,
        }

    def cancel(self, job_id: str) -> dict:
        assert self._lock.held is True
        self.cancelled.append(job_id)
        return {"job_id": job_id, "status": "canceled"}


def _authority(monkeypatch, fake: FakeManager, *, revision: str = REVISION) -> None:
    monkeypatch.setattr(revision_bound, "manager", fake)
    monkeypatch.setattr(
        revision_bound,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": revision},
    )


def test_revision_bound_enqueue_stays_inside_authority_lock(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)

    result = revision_bound.start_revision_bound_body_build(
        PERSON_ID,
        expected_bodyrig_revision=REVISION,
    )

    assert result["bodyrig_revision"] == REVISION
    assert "ab_baseline_retention" not in result
    assert fake.started == 1
    assert fake.cancelled == []
    assert fake._lock.held is False


def test_explicit_ab_retention_is_persisted_while_worker_is_locked(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)
    queued = {
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "queued",
        "bodyrig_revision": REVISION,
    }
    writes: list[dict] = []

    def _read(_path):
        assert fake._lock.held is True
        return dict(queued)

    def _write(job: dict) -> None:
        assert fake._lock.held is True
        writes.append(dict(job))

    monkeypatch.setattr(revision_bound, "_read_job", _read)
    monkeypatch.setattr(revision_bound, "_write_job", _write)

    result = revision_bound.start_revision_bound_body_build(
        PERSON_ID,
        expected_bodyrig_revision=REVISION,
        retain_private_workspace_for_ab=True,
    )

    marker = result["ab_baseline_retention"]
    assert marker == {
        "format": "bodyrig-ab-baseline-retention",
        "version": 1,
        "retain_private_workspace": True,
        "expected_bodyrig_revision": REVISION,
        "job_id": JOB_ID,
    }
    assert writes[-1]["ab_baseline_retention"] == marker
    assert fake.cancelled == []
    assert fake._lock.held is False


def test_ab_retention_write_failure_cancels_job_before_unlock(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)
    queued = {
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "queued",
        "bodyrig_revision": REVISION,
    }
    monkeypatch.setattr(revision_bound, "_read_job", lambda _path: dict(queued))

    def _write(_job: dict) -> None:
        assert fake._lock.held is True
        raise OSError("disk write failed")

    monkeypatch.setattr(revision_bound, "_write_job", _write)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="canceled queued job",
    ):
        revision_bound.start_revision_bound_body_build(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            retain_private_workspace_for_ab=True,
        )

    assert fake.cancelled == [JOB_ID]
    assert fake._lock.held is False


def test_revision_drift_during_enqueue_cancels_queued_job_before_unlock(monkeypatch) -> None:
    fake = FakeManager(OTHER_REVISION)
    _authority(monkeypatch, fake)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="canceled queued job",
    ):
        revision_bound.start_revision_bound_body_build(
            "person-" + "3" * 32,
            expected_bodyrig_revision=REVISION,
        )

    assert fake.started == 1
    assert fake.cancelled == [JOB_ID]
    assert fake._lock.held is False


def test_revision_mismatch_before_enqueue_refuses_without_creating_job(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake, revision=OTHER_REVISION)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="differs from requested authority",
    ):
        revision_bound.start_revision_bound_body_build(
            "person-" + "4" * 32,
            expected_bodyrig_revision=REVISION,
        )

    assert fake.started == 0
    assert fake.cancelled == []
