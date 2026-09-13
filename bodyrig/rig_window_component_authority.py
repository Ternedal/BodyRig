from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError
from .high_fidelity_preview_list_cli import HighFidelityPreviewListError, list_recent_previews
from .renderer_human_rejection import RendererHumanRejectionError, read_rejection
from .renderer_human_rejection_cli import _binding, _expected
from . import rig_window_authority_policy as authority


HIGH_FIDELITY_COMPONENT_CHECKS = frozenset(
    {
        "hair_appearance",
        "eye_appearance",
        "face_secondary",
        "small_anatomical_detail",
    }
)
BROAD_COMPONENT_REBUILD_CHECKS = frozenset(
    {
        "hair_appearance",
        "eye_appearance",
        "small_anatomical_detail",
    }
)
_PREVIEW_ACTIVE = frozenset({"queued", "running", "succeeded"})
_PREVIEW_RETRYABLE = frozenset({"failed", "interrupted"})
_TARGET_FAMILIES = frozenset({"female", "male", "neutral"})


def _validated_failed_checks(acceptance_dir: str | Path) -> frozenset[str]:
    root = Path(acceptance_dir).expanduser().resolve()
    gate, paths = _binding(root, "windows-unity-univrm")
    receipt = read_rejection(
        root,
        platform="windows-unity-univrm",
        **_expected(gate, paths),
    )
    failures = receipt.get("failed_checks")
    if not isinstance(failures, list):
        raise RendererHumanRejectionError("renderer human rejection failed_checks are unavailable")
    return frozenset(str(value) for value in failures)


def _block(plan: dict[str, Any], rationale: str) -> dict[str, Any]:
    routed = dict(plan)
    routed.update(
        state="blocked",
        path="human-fidelity-rework-blocked",
        next_command=None,
        rationale=rationale,
    )
    return routed


def _body_job_id_from_acceptance(acceptance_dir: str) -> str:
    try:
        body_job_id = Path(acceptance_dir).expanduser().resolve(strict=False).parent.name.lower()
    except (OSError, RuntimeError, ValueError):
        return ""
    return body_job_id if authority.policy.base.JOB_ID.fullmatch(body_job_id) else ""


def _select_ui_rejection_rework(
    *,
    repo_root: Path,
    preferred_job_id: str = "",
    person_id: str = "",
    performer_id: str = "",
    body_id: str = "",
) -> dict[str, Any] | None:
    """Recover canonical rejected UI acceptances dropped by normal progress ranking.

    The normal structural acceptance rank is intentionally zero after a human
    rejection, so the base planner omits the acceptance. Recover only an exact
    scoped UI-job rejection. When the caller did not supply BodyId, derive it
    from the validated rejection and fail closed if more than one BodyId remains.
    """

    repo_root = Path(repo_root).expanduser().resolve()
    base = authority.policy.base
    head = base._head(repo_root)
    root = base.data_dir()
    all_rows = base._job_rows(root)
    resolved_person, resolved_performer = base.resolve_person_scope(
        root=root,
        rows=all_rows,
        preferred_job_id=preferred_job_id,
        person_id=person_id,
        performer_id=performer_id,
    )
    rows = base._scope_rows(all_rows, person_id=resolved_person, performer_requested=bool(performer_id))
    scoped_performer = resolved_performer or performer_id
    if not scoped_performer:
        return None

    rejected: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "") != "succeeded":
            continue
        acceptance_text = str(row.get("acceptance_dir") or "").strip()
        if not acceptance_text:
            continue
        try:
            acceptance_dir = Path(acceptance_text).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if not (acceptance_dir / "bodyrig-acceptance.json").is_file():
            continue
        try:
            payload = base.inspect_for_rig_window(acceptance_dir)
        except Exception:
            continue
        if payload.get("state") != "blocked" or payload.get("gate") != "windows-rejected":
            continue
        candidate_body_id = str(payload.get("body_id") or "").strip()
        if not candidate_body_id:
            continue
        if body_id and candidate_body_id != body_id:
            continue
        revision = str(payload.get("bodyrig_revision") or "").strip().lower()
        if not base.SHA40.fullmatch(revision):
            continue
        if revision != head and not base._historical_revision_is_safe(repo_root, revision):
            continue
        job_id = str(row.get("job_id") or "").strip().lower()
        if not base.JOB_ID.fullmatch(job_id):
            continue
        rejected.append(
            {
                "job_id": job_id,
                "body_id": candidate_body_id,
                "acceptance_dir": str(acceptance_dir),
                "evidence_revision": revision,
                "stamp": str(row.get("stamp") or ""),
            }
        )

    if not rejected:
        return None

    if not body_id and preferred_job_id:
        preferred = [item for item in rejected if item["job_id"] == preferred_job_id]
        if preferred:
            rejected = preferred

    if not body_id:
        body_ids = sorted({str(item["body_id"]) for item in rejected})
        if len(body_ids) > 1:
            raise base.RigWindowPlanError(
                "Rejected UI fidelity evidence belongs to multiple BodyIds; pass -BodyId with the intended scoped rejection: "
                + ", ".join(body_ids)
            )
        body_id = body_ids[0]

    rejected.sort(
        key=lambda item: (
            bool(preferred_job_id and item["job_id"] == preferred_job_id),
            item["stamp"],
        ),
        reverse=True,
    )
    selected = rejected[0]

    result = authority.policy._base_result(
        head,
        rank=authority.policy.HUMAN_FIDELITY_REWORK_RANK,
        path="human-fidelity-rework",
        resolved_person=resolved_person,
        resolved_performer=scoped_performer,
        requested_body=body_id,
    )
    result.update(
        {
            "evidence_revision": selected["evidence_revision"],
            "session_report": None,
            "acceptance_dir": selected["acceptance_dir"],
            "gate": "windows-rejected",
            "expensive_reconstruction_rerun": True,
            "fitter_rerun": True,
            "rationale": (
                "Human visual review rejected the scoped UI-job Windows fidelity output. Preserve that exact rejection "
                "as rework authority instead of discarding rank-0 evidence and falling through to fresh reconstruction."
            ),
            "next_command": (
                f".\\run-profiled-fidelity-convergence.ps1 -PerformerId {base._ps_quote(scoped_performer)} "
                f"-BodyId {base._ps_quote(body_id)} -KeepPrivateWorkspaces"
            ),
        }
    )
    return result


def _historical_status_command(*, revision: str, preview_job_id: str, head: str) -> str:
    quoted_preview = authority.policy.base._ps_quote(preview_job_id)
    if revision == head:
        return f".\\high-fidelity-physical-status.ps1 -PreviewJobId {quoted_preview}"
    quoted_revision = authority.policy.base._ps_quote(revision)
    return (
        f"& .\\update-windows.ps1 -Revision {quoted_revision} -NoBrowser -SkipPlan; "
        "if ($?) { "
        f"$legacyStatusJson = @(& .\\high-fidelity-physical-status.ps1 -PreviewJobId {quoted_preview} -Json); "
        "if ($?) { "
        "$legacyStatus = (($legacyStatusJson -join [Environment]::NewLine) | ConvertFrom-Json); "
        "if ($legacyStatus.high_fidelity_complete -eq $true) { "
        "& .\\update-windows.ps1 -NoBrowser -SkipPlan; "
        f"if ($?) {{ & .\\high-fidelity-physical-status.ps1 -PreviewJobId {quoted_preview} }} "
        "} else { "
        f"& .\\high-fidelity-physical-status.ps1 -PreviewJobId {quoted_preview} "
        "} "
        "} "
        "}"
    )


def _preview_start_command(
    *,
    person_id: str,
    body_job_id: str,
    target_family: str,
    revision: str,
) -> str:
    return (
        ".\\start-high-fidelity-preview-from-body-job.ps1 "
        f"-PersonId {authority.policy.base._ps_quote(person_id)} "
        f"-BodyJobId {authority.policy.base._ps_quote(body_job_id)} "
        f"-TargetFamily {authority.policy.base._ps_quote(target_family)} "
        f"-Revision {authority.policy.base._ps_quote(revision)}"
    )


def _route_to_preview_authority(
    plan: dict[str, Any],
    *,
    person_id: str,
    body_job_id: str,
    revision: str,
) -> dict[str, Any]:
    try:
        rows = list_recent_previews(
            limit=100,
            succeeded_only=False,
            person_id=person_id,
            body_job_id=body_job_id,
        )
    except HighFidelityPreviewListError as exc:
        return _block(
            plan,
            f"Exact high-fidelity preview discovery failed before rework routing: {exc}",
        )

    exact = [
        row
        for row in rows
        if str(row.get("bodyrig_revision") or "").strip().lower() == revision
        and str(row.get("target_family") or "").strip().lower() in _TARGET_FAMILIES
    ]
    active = [row for row in exact if str(row.get("status") or "") in _PREVIEW_ACTIVE]
    retryable = [row for row in exact if str(row.get("status") or "") in _PREVIEW_RETRYABLE]
    selected = active[0] if active else (retryable[0] if retryable else None)

    routed = dict(plan)
    routed.update(
        path="high-fidelity-component-rework",
        body_job_id=body_job_id,
        expensive_reconstruction_rerun=False,
        fitter_rerun=False,
    )

    if selected is not None:
        preview_job_id = str(selected.get("job_id") or "")
        target_family = str(selected.get("target_family") or "").strip().lower()
        status = str(selected.get("status") or "")
        component_failures = frozenset(str(value) for value in (plan.get("component_failed_checks") or []))
        if status == "succeeded" and BROAD_COMPONENT_REBUILD_CHECKS.issubset(component_failures):
            escalated = dict(plan)
            escalated.update(
                path="human-fidelity-rework",
                preview_job_id=preview_job_id,
                target_family=target_family,
                body_job_id=body_job_id,
                expensive_reconstruction_rerun=True,
                fitter_rerun=True,
                operator_input_required=False,
                rationale=(
                    "Human review rejected hair, eyes and small anatomical detail after this exact high-fidelity "
                    "preview already succeeded. Re-entering the same retained preview can only repeat the rejected "
                    "visual base, so escalate to the existing profiled reconstruction/fitter rework path instead."
                ),
            )
            return escalated
        routed["preview_job_id"] = preview_job_id
        routed["target_family"] = target_family
        if status == "succeeded":
            routed.update(
                rationale=(
                    "Human review rejected only addressable high-fidelity component domains and an exact scoped "
                    "succeeded preview already exists. Re-enter its producer revision for unfinished legacy "
                    "anatomy/hair/eyes/face-secondary gates; once that chain proves complete, return to current "
                    "integration authority for HFN instead of rewriting historical evidence."
                ),
                next_command=_historical_status_command(
                    revision=revision,
                    preview_job_id=preview_job_id,
                    head=str(plan.get("bodyrig_revision") or "").strip().lower(),
                ),
                operator_input_required=False,
            )
            return routed

        routed.update(
            rationale=(
                "Human review rejected only addressable high-fidelity component domains. The exact scoped preview "
                f"authority is {status}; re-enter the baseline producer revision and start/resume the preview so the "
                "planner action changes persistent state rather than looping on read-only discovery."
            ),
            next_command=_preview_start_command(
                person_id=person_id,
                body_job_id=body_job_id,
                target_family=target_family,
                revision=revision,
            ),
            operator_input_required=False,
        )
        return routed

    routed.update(
        rationale=(
            "Human review rejected only addressable high-fidelity component domains and no exact scoped preview "
            "exists yet. Start the revision-bound high-fidelity preview from the retained baseline body. Target "
            "family remains explicit operator input; BodyRig does not infer it from identity or appearance."
        ),
        next_command=_preview_start_command(
            person_id=person_id,
            body_job_id=body_job_id,
            target_family="<TARGET_FAMILY>",
            revision=revision,
        ),
        operator_input_required=True,
        required_operator_input={"target_family": ["female", "male", "neutral"]},
    )
    return routed


def route_component_fidelity_rework(plan: dict[str, Any]) -> dict[str, Any]:
    if str(plan.get("path") or "") != "human-fidelity-rework":
        return plan
    if str(plan.get("gate") or "") != "windows-rejected":
        return plan

    acceptance_dir = str(plan.get("acceptance_dir") or "").strip()
    if not acceptance_dir:
        return _block(
            plan,
            "Human fidelity rejection was selected without an acceptance directory. "
            "Do not rerun reconstruction until the rejection authority can be rebound.",
        )

    try:
        failed_checks = _validated_failed_checks(acceptance_dir)
    except (AcceptanceStatusError, RendererHumanRejectionError, OSError, RuntimeError, ValueError) as exc:
        return _block(
            plan,
            "Selected human fidelity rejection could not be revalidated before routing. "
            f"Do not spend rig time on a guessed rework path: {exc}",
        )

    component_failures = failed_checks & HIGH_FIDELITY_COMPONENT_CHECKS
    if not component_failures:
        return plan

    non_component_failures = failed_checks - HIGH_FIDELITY_COMPONENT_CHECKS
    if non_component_failures:
        return plan

    scope = plan.get("scope")
    person_id = str(scope.get("person_id") or "").strip().lower() if isinstance(scope, dict) else ""
    body_job_id = _body_job_id_from_acceptance(acceptance_dir)
    revision = str(plan.get("evidence_revision") or "").strip().lower()
    if (
        not authority.policy.base.PERSON_ID.fullmatch(person_id)
        or not body_job_id
        or not authority.policy.base.SHA40.fullmatch(revision)
    ):
        return _block(
            plan,
            "Component-specific rejection is valid, but the planner cannot bind it to one exact Person/body job/producer "
            "revision for high-fidelity continuation.",
        )

    route_seed = dict(plan)
    route_seed["failed_checks"] = sorted(failed_checks)
    route_seed["component_failed_checks"] = sorted(component_failures)
    routed = _route_to_preview_authority(
        route_seed,
        person_id=person_id,
        body_job_id=body_job_id,
        revision=revision,
    )
    routed["failed_checks"] = sorted(failed_checks)
    routed["component_failed_checks"] = sorted(component_failures)
    return routed


def build_plan(**kwargs: Any) -> dict[str, Any]:
    plan = authority.build_plan(**kwargs)
    if (
        str(plan.get("path") or "") != "human-fidelity-rework"
        and int(plan.get("progress_rank") or 0) <= authority.policy.HUMAN_FIDELITY_REWORK_RANK
    ):
        ui_rework = _select_ui_rejection_rework(**kwargs)
        if ui_rework is not None:
            plan = ui_rework
    return route_component_fidelity_rework(plan)


def main(argv: list[str] | None = None) -> int:
    args = authority.policy._parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
        return 2
    if args.preferred_job_id and not authority.policy.base.JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    if args.person_id and not authority.policy.base.PERSON_ID.fullmatch(args.person_id):
        print("BodyRig rig-window plan: ERROR | person id is invalid.", file=sys.stderr)
        return 2
    try:
        plan = build_plan(
            repo_root=args.repo_root,
            preferred_job_id=args.preferred_job_id,
            person_id=args.person_id,
            performer_id=args.performer_id,
            body_id=args.body_id,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"BodyRig rig-window plan: ERROR | {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    else:
        print(authority.policy._render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
