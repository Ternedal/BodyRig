from __future__ import annotations

from typing import Any

from .ui_jobs import UiJobError, manager, operator_checkout_status


class RevisionBoundBodyBuildError(UiJobError):
    pass


def _canonical_revision(value: object, *, label: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise RevisionBoundBodyBuildError(f"{label} is not an exact 40-character Git revision")
    return revision


def start_revision_bound_body_build(person_id: str, *, expected_bodyrig_revision: str) -> dict[str, Any]:
    expected = _canonical_revision(expected_bodyrig_revision, label="expected BodyRig revision")

    # UiJobManager.start_body_build starts its worker thread before returning.
    # Holding its RLock across this complete sequence keeps that worker blocked
    # in _run_body_build until we have verified the returned queued job. If the
    # checkout changes between the preflight authority probe and enqueue, the
    # job is canceled while still queued before this lock is released.
    with manager._lock:  # noqa: SLF001 - deliberate cross-method authority transaction
        authority = operator_checkout_status()
        if not authority.get("ok"):
            raise RevisionBoundBodyBuildError(
                str(authority.get("reason") or "BodyRig operator checkout is not authoritative")
            )
        actual = _canonical_revision(authority.get("revision"), label="BodyRig operator checkout revision")
        if actual != expected:
            raise RevisionBoundBodyBuildError(
                f"BodyRig operator checkout revision differs from requested authority: expected {expected}, got {actual}"
            )

        started = manager.start_body_build(person_id, feedback="", changes=None)
        job_revision = _canonical_revision(started.get("bodyrig_revision"), label="enqueued body-build revision")
        if job_revision != expected:
            job_id = str(started.get("job_id") or "")
            if not job_id:
                raise RevisionBoundBodyBuildError(
                    "body-build revision changed during enqueue and no job id was returned for safe cancellation"
                )
            try:
                manager.cancel(job_id)
            except UiJobError as exc:
                raise RevisionBoundBodyBuildError(
                    "body-build revision changed during enqueue and the queued job could not be canceled safely"
                ) from exc
            raise RevisionBoundBodyBuildError(
                f"body-build revision changed during enqueue; canceled queued job {job_id} before physical start"
            )
        return started
