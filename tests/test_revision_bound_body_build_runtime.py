from __future__ import annotations

import pytest

import bodyrig.revision_bound_body_build as revision_bound


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
JOB_ID = "job-" + "1" * 32


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


def test_revision_bound_enqueue_stays_inside_authority_lock(monkeypatch) -> None:
    fake = FakeManager(REVISION)
    monkeypatch.setattr(revision_bound, "manager", fake)
    monkeypatch.setattr(
        revision_bound,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": REVISION},
    )

    result = revision_bound.start_revision_bound_body_build(
        "person-" + "2" * 32,
        expected_bodyrig_revision=REVISION,
    )

    assert result["bodyrig_revision"] == REVISION
    assert fake.started == 1
    assert fake.cancelled == []
    assert fake._lock.held is False


def test_revision_drift_during_enqueue_cancels_queued_job_before_unlock(monkeypatch) -> None:
    fake = FakeManager(OTHER_REVISION)
    monkeypatch.setattr(revision_bound, "manager", fake)
    monkeypatch.setattr(
        revision_bound,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": REVISION},
    )

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
    monkeypatch.setattr(revision_bound, "manager", fake)
    monkeypatch.setattr(
        revision_bound,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": OTHER_REVISION},
    )

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
