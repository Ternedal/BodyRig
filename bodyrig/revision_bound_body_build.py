from __future__ import annotations

from typing import Any

from .ui_jobs import UiJobError, _job_path, _read_job, _write_job, manager, operator_checkout_status


class RevisionBoundBodyBuildError(UiJobError):
    pass


def _canonical_revision(value: object, *, label: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise RevisionBoundBodyBuildError(f"{label} is not an exact 40-character Git revision")
    return revision


def _cancel_queued_or_fail(job_id: str, *, reason: str) -> None:
    try:
        manager.cancel(job_id)
    except UiJobError as exc:
        raise RevisionBoundBodyBuildError(
            f"{reason}; the queued body-build could not be canceled safely"
        ) from exc


def start_revision_bound_body_build(
    person_id: str,
    *,
    expected_bodyrig_revision: str,
    retain_private_workspace_for_ab: bool = False,
) -> dict[str, Any]:
    expected = _canonical_revision(expected_bodyrig_revision, label="expected BodyRig revision")

    # UiJobManager.start_body_build starts its worker thread before returning.
    # Holding its RLock across this complete sequence keeps that worker blocked
    # in _run_body_build until we have verified the returned queued job. If the
    # checkout changes between the preflight authority probe and enqueue, or an
    # explicit A/B retention marker cannot be persisted, the job is canceled
    # while still queued before this lock is released.
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
            _cancel_queued_or_fail(
                job_id,
                reason="body-build revision changed during enqueue",
            )
            raise RevisionBoundBodyBuildError(
                f"body-build revision changed during enqueue; canceled queued job {job_id} before physical start"
            )

        if retain_private_workspace_for_ab:
            job_id = str(started.get("job_id") or "")
            if not job_id:
                raise RevisionBoundBodyBuildError("A/B retention request did not receive a canonical queued job id")
            try:
                queued = _read_job(_job_path(job_id))
                if queued.get("status") != "queued" or queued.get("kind") != "body-build":
                    raise RevisionBoundBodyBuildError(
                        "A/B private-workspace retention can only be bound while the exact body-build is still queued"
                    )
                queued_revision = _canonical_revision(
                    queued.get("bodyrig_revision"),
                    label="queued A/B baseline body-build revision",
                )
                if queued_revision != expected:
                    raise RevisionBoundBodyBuildError(
                        "queued A/B baseline body-build revision changed before retention could be bound"
                    )
                queued["ab_baseline_retention"] = {
                    "format": "bodyrig-ab-baseline-retention",
                    "version": 1,
                    "retain_private_workspace": True,
                    "expected_bodyrig_revision": expected,
                    "job_id": job_id,
                }
                _write_job(queued)
                started = dict(queued)
            except (OSError, UiJobError, RevisionBoundBodyBuildError) as exc:
                _cancel_queued_or_fail(
                    job_id,
                    reason="A/B private-workspace retention could not be persisted before physical start",
                )
                raise RevisionBoundBodyBuildError(
                    f"A/B private-workspace retention failed; canceled queued job {job_id} before physical start"
                ) from exc

        return started
