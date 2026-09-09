from __future__ import annotations

import pytest

import bodyrig.revision_bound_body_build as revision_bound


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
PERFORMER_ID = "stash-performer-42"
OTHER_PERFORMER_ID = "stash-performer-99"


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
        self.performer_id = PERFORMER_ID
        self.performer_after_start: str | None = None
        self.started = 0
        self.cancelled: list[str] = []
        self.writes: list[dict] = []
        self.queued: dict = {}

    def start_body_build(self, person_id: str, *, feedback: str, changes) -> dict:
        assert self._lock.held is True
        assert feedback == ""
        assert changes is None
        self.started += 1
        self.queued = {
            "format": "bodyrig-ui-job",
            "version": 1,
            "job_id": JOB_ID,
            "kind": "body-build",
            "person_id": person_id,
            "status": "queued",
            "bodyrig_revision": self.job_revision,
        }
        if self.performer_after_start is not None:
            self.performer_id = self.performer_after_start
        return dict(self.queued)

    def cancel(self, job_id: str) -> dict:
        assert self._lock.held is True
        self.cancelled.append(job_id)
        self.queued["status"] = "canceled"
        return {"job_id": job_id, "status": "canceled"}


def _authority(monkeypatch, fake: FakeManager, *, revision: str = REVISION) -> None:
    monkeypatch.setattr(revision_bound, "manager", fake)
    monkeypatch.setattr(
        revision_bound,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": revision},
    )
    monkeypatch.setattr(
        revision_bound,
        "_current_stash_performer_id",
        lambda _person_id: fake.performer_id,
    )
    monkeypatch.setattr(revision_bound, "_read_job", lambda _path: dict(fake.queued))

    def _write(job: dict) -> None:
        assert fake._lock.held is True
        fake.queued = dict(job)
        fake.writes.append(dict(job))

    monkeypatch.setattr(revision_bound, "_write_job", _write)


def _start(fake: FakeManager, *, retain: bool = False) -> dict:
    return revision_bound.start_revision_bound_body_build(
        PERSON_ID,
        expected_bodyrig_revision=REVISION,
        expected_stash_performer_id=PERFORMER_ID,
        retain_private_workspace_for_ab=retain,
    )


def test_revision_bound_enqueue_stays_inside_authority_lock_and_persists_source(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)

    result = _start(fake)

    assert result["bodyrig_revision"] == REVISION
    assert "ab_baseline_retention" not in result
    assert result["source_enqueue_authority"] == {
        "format": "bodyrig-body-build-source-enqueue-authority",
        "version": 1,
        "job_id": JOB_ID,
        "person_id": PERSON_ID,
        "stash_performer_id": PERFORMER_ID,
        "expected_bodyrig_revision": REVISION,
    }
    assert fake.started == 1
    assert fake.cancelled == []
    assert fake.writes[-1]["source_enqueue_authority"] == result["source_enqueue_authority"]
    assert fake._lock.held is False


def test_explicit_ab_retention_and_source_authority_are_persisted_together(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)

    result = _start(fake, retain=True)

    marker = result["ab_baseline_retention"]
    assert marker == {
        "format": "bodyrig-ab-baseline-retention",
        "version": 1,
        "retain_private_workspace": True,
        "expected_bodyrig_revision": REVISION,
        "job_id": JOB_ID,
    }
    assert fake.writes[-1]["ab_baseline_retention"] == marker
    assert fake.writes[-1]["source_enqueue_authority"]["stash_performer_id"] == PERFORMER_ID
    assert fake.cancelled == []
    assert fake._lock.held is False


def test_source_authority_write_failure_cancels_job_before_unlock(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    _authority(monkeypatch, fake)

    def _write(_job: dict) -> None:
        assert fake._lock.held is True
        raise OSError("disk write failed")

    monkeypatch.setattr(revision_bound, "_write_job", _write)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="canceled queued job",
    ):
        _start(fake, retain=True)

    assert fake.cancelled == [JOB_ID]
    assert fake._lock.held is False


def test_revision_drift_during_enqueue_cancels_queued_job_before_unlock(monkeypatch) -> None:
    fake = FakeManager(OTHER_REVISION)
    _authority(monkeypatch, fake)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="canceled queued job",
    ):
        _start(fake)

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
        _start(fake)

    assert fake.started == 0
    assert fake.cancelled == []


def test_source_mismatch_before_enqueue_refuses_without_creating_job(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    fake.performer_id = OTHER_PERFORMER_ID
    _authority(monkeypatch, fake)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="differs from requested source authority before enqueue",
    ):
        _start(fake)

    assert fake.started == 0
    assert fake.cancelled == []


def test_source_drift_during_enqueue_cancels_before_worker_can_start(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    fake.performer_after_start = OTHER_PERFORMER_ID
    _authority(monkeypatch, fake)

    with pytest.raises(
        revision_bound.RevisionBoundBodyBuildError,
        match="canceled queued job",
    ):
        _start(fake)

    assert fake.started == 1
    assert fake.cancelled == [JOB_ID]
    assert fake._lock.held is False
