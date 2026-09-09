from __future__ import annotations

from typing import Any, Mapping

from .person_profiles import PersonProfileError, load_profile
from .storage import person_library
from .ui_jobs import UiJobError, _job_path, _read_job, _write_job, manager, operator_checkout_status


class RevisionBoundBodyBuildError(UiJobError):
    pass


def _canonical_revision(value: object, *, label: str) -> str:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise RevisionBoundBodyBuildError(f"{label} is not an exact 40-character Git revision")
    return revision


def _expected_performer_id(value: object) -> str:
    performer_id = str(value or "").strip()
    if not performer_id or len(performer_id) > 256:
        raise RevisionBoundBodyBuildError("expected Stash performer id is missing or invalid")
    return performer_id


def _current_stash_performer_id(person_id: str) -> str:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise RevisionBoundBodyBuildError("BodyRig Person profile is no longer valid") from exc
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise RevisionBoundBodyBuildError("Person must remain bound to one Stash performer for revision-bound body build")
    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        raise RevisionBoundBodyBuildError("Person Stash performer binding is missing its performer id")
    return performer_id


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
    expected_stash_performer_id: str,
    retain_private_workspace_for_ab: bool = False,
) -> dict[str, Any]:
    expected = _canonical_revision(expected_bodyrig_revision, label="expected BodyRig revision")
    expected_performer = _expected_performer_id(expected_stash_performer_id)

    # UiJobManager.start_body_build starts its worker thread before returning.
    # Holding its RLock across this complete sequence keeps that worker blocked
    # in _run_body_build until we have verified both checkout and source identity,
    # then persisted the exact source enqueue authority. Point-of-use checks in
    # UiJobManager reject later Person/source drift before every physical child
    # process is started.
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
        before_performer = _current_stash_performer_id(person_id)
        if before_performer != expected_performer:
            raise RevisionBoundBodyBuildError(
                "Person Stash performer differs from requested source authority before enqueue: "
                f"expected {expected_performer}, got {before_performer}"
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

        job_id = str(started.get("job_id") or "")
        if not job_id:
            raise RevisionBoundBodyBuildError("revision-bound body-build did not receive a canonical queued job id")
        try:
            queued = _read_job(_job_path(job_id))
            if queued.get("status") != "queued" or queued.get("kind") != "body-build":
                raise RevisionBoundBodyBuildError(
                    "revision-bound source authority can only be bound while the exact body-build is still queued"
                )
            queued_revision = _canonical_revision(
                queued.get("bodyrig_revision"),
                label="queued revision-bound body-build revision",
            )
            if queued_revision != expected:
                raise RevisionBoundBodyBuildError(
                    "queued revision-bound body-build revision changed before source authority could be bound"
                )
            if str(queued.get("person_id") or "") != person_id:
                raise RevisionBoundBodyBuildError(
                    "queued revision-bound body-build Person identity changed before source authority could be bound"
                )
            after_performer = _current_stash_performer_id(person_id)
            if after_performer != expected_performer:
                raise RevisionBoundBodyBuildError(
                    "Person Stash performer changed during enqueue before physical start"
                )
            queued["source_enqueue_authority"] = {
                "format": "bodyrig-body-build-source-enqueue-authority",
                "version": 1,
                "job_id": job_id,
                "person_id": person_id,
                "stash_performer_id": expected_performer,
                "expected_bodyrig_revision": expected,
            }
            if retain_private_workspace_for_ab:
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
                reason="revision-bound source/retention authority could not be persisted before physical start",
            )
            raise RevisionBoundBodyBuildError(
                f"revision-bound source/retention authority failed; canceled queued job {job_id} before physical start"
            ) from exc

        return started
