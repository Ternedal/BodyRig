from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import high_fidelity_continuation_status_legacy as legacy_status
from . import rig_window_component_authority as component
from .high_fidelity_hfn_migration import HighFidelityHfnMigrationError, read_migration

ADDRESSABLE_CHECKS = frozenset({
    "hair_appearance",
    "eye_appearance",
    "face_secondary",
    "small_anatomical_detail",
})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _body_convergence(plan: dict[str, Any]) -> dict[str, Any]:
    scope = plan.get("scope") if isinstance(plan.get("scope"), dict) else {}
    performer = str(scope.get("performer_id") or "").strip()
    body_id = str(scope.get("body_id") or "").strip()
    if not performer or not body_id:
        return component._block(plan, "Mixed human-fidelity rejection lacks exact performer/body scope for body convergence.")
    base = component.authority.policy.base
    routed = dict(plan)
    routed.update(
        state="ready",
        path="human-fidelity-rework",
        expensive_reconstruction_rerun=True,
        fitter_rerun=True,
        rationale=(
            "Human review rejected both high-fidelity component detail and body/deformation domains. "
            "Preserve body convergence before component-only continuation."
        ),
        next_command=(
            f".\\run-profiled-fidelity-convergence.ps1 -PerformerId {base._ps_quote(performer)} "
            f"-BodyId {base._ps_quote(body_id)} -KeepPrivateWorkspaces"
        ),
    )
    return routed


def _migration_status_command(*, integration_revision: str, preview_job_id: str, head: str) -> str:
    quote = component.authority.policy.base._ps_quote
    if integration_revision == head:
        return f".\\high-fidelity-hfn-migrated-status.ps1 -PreviewJobId {quote(preview_job_id)}"
    return (
        f"& .\\update-windows.ps1 -Revision {quote(integration_revision)} -NoBrowser; "
        f"if ($?) {{ & .\\high-fidelity-hfn-migrated-status.ps1 -PreviewJobId {quote(preview_job_id)} }}"
    )


def _route_small_detail(plan: dict[str, Any]) -> dict[str, Any]:
    failed = frozenset(str(value) for value in plan.get("failed_checks") or [])
    if "small_anatomical_detail" not in failed:
        return plan
    if failed - ADDRESSABLE_CHECKS:
        return _body_convergence(plan)

    acceptance_dir = str(plan.get("acceptance_dir") or "").strip()
    scope = plan.get("scope") if isinstance(plan.get("scope"), dict) else {}
    person_id = str(scope.get("person_id") or "").strip().lower()
    body_job_id = component._body_job_id_from_acceptance(acceptance_dir)
    source_revision = str(plan.get("evidence_revision") or "").strip().lower()
    head = str(plan.get("bodyrig_revision") or "").strip().lower()
    base = component.authority.policy.base
    if (
        not base.PERSON_ID.fullmatch(person_id)
        or not body_job_id
        or not base.SHA40.fullmatch(source_revision)
        or not base.SHA40.fullmatch(head)
    ):
        return component._block(
            plan,
            "Small-detail rejection is valid but cannot be bound to one exact Person/body job/source revision/current revision.",
        )

    try:
        rows = component.list_recent_previews(
            limit=100,
            succeeded_only=False,
            person_id=person_id,
            body_job_id=body_job_id,
        )
    except component.HighFidelityPreviewListError as exc:
        return component._block(plan, f"HFN preview discovery failed: {exc}")
    exact = [
        row for row in rows
        if str(row.get("bodyrig_revision") or "").strip().lower() == source_revision
        and str(row.get("target_family") or "").strip().lower() in component._TARGET_FAMILIES
    ]
    active = [row for row in exact if str(row.get("status") or "") in component._PREVIEW_ACTIVE]
    retryable = [row for row in exact if str(row.get("status") or "") in component._PREVIEW_RETRYABLE]
    selected = active[0] if active else (retryable[0] if retryable else None)

    routed = dict(plan)
    routed.update(
        state="ready",
        path="high-fidelity-component-rework",
        body_job_id=body_job_id,
        failed_checks=sorted(failed),
        component_failed_checks=sorted(failed),
        expensive_reconstruction_rerun=False,
        fitter_rerun=False,
    )

    if selected is None:
        routed.update(
            rationale=(
                "Human review rejected addressable high-fidelity component detail, including HFN. "
                "No exact historical preview exists yet; start the retained baseline preview without rerunning reconstruction."
            ),
            next_command=component._preview_start_command(
                person_id=person_id,
                body_job_id=body_job_id,
                target_family="<TARGET_FAMILY>",
                revision=source_revision,
            ),
            operator_input_required=True,
            required_operator_input={"target_family": ["female", "male", "neutral"]},
        )
        return routed

    preview_job_id = str(selected.get("job_id") or "")
    target_family = str(selected.get("target_family") or "").strip().lower()
    status = str(selected.get("status") or "")
    routed["preview_job_id"] = preview_job_id
    routed["target_family"] = target_family

    if status != "succeeded":
        routed.update(
            rationale=f"Exact historical preview is {status}; start/resume it on its producer revision before HFN migration.",
            next_command=component._preview_start_command(
                person_id=person_id,
                body_job_id=body_job_id,
                target_family=target_family,
                revision=source_revision,
            ),
            operator_input_required=False,
        )
        return routed

    try:
        legacy = legacy_status.inspect_continuation(preview_job_id)
    except Exception as exc:
        return component._block(plan, f"Historical high-fidelity continuation could not be revalidated: {exc}")

    if legacy.get("high_fidelity_complete") is not True:
        routed.update(
            rationale=(
                "Historical preview exists, but its anatomy/hair/eyes/face-secondary continuation is not complete. "
                "Finish those producer-revision gates before current-main HFN migration."
            ),
            next_command=component._historical_status_command(
                revision=source_revision,
                preview_job_id=preview_job_id,
                head=head,
            ),
            operator_input_required=False,
        )
        return routed

    package_value = str(legacy.get("current_package_path") or "").strip()
    package_sha = str(legacy.get("current_package_sha256") or "").strip().lower()
    package_path = Path(package_value).expanduser().resolve() if package_value else None
    if (
        package_path is None
        or not package_path.is_file()
        or not SHA256_RE.fullmatch(package_sha)
        or _sha256(package_path) != package_sha
    ):
        return component._block(plan, "Historical promoted package bytes are missing or no longer match continuation authority.")

    if source_revision == head:
        routed.update(
            rationale="Legacy component continuation and HFN software share the same current revision; continue canonical status directly.",
            next_command=f".\\high-fidelity-physical-status.ps1 -PreviewJobId {base._ps_quote(preview_job_id)}",
            operator_input_required=False,
        )
        return routed

    try:
        migration = read_migration(
            preview_job_id,
            source_bodyrig_revision=source_revision,
            source_package_sha256=package_sha,
        )
    except HighFidelityHfnMigrationError as exc:
        return component._block(plan, f"Existing HFN migration authority is invalid: {exc}")

    if migration is None:
        routed.update(
            rationale=(
                "Historical anatomy/hair/eyes/face-secondary continuation is complete. Create an explicit review-only "
                "current-integration HFN migration for the exact promoted package bytes before nail/detail application."
            ),
            next_command=f".\\prepare-high-fidelity-hfn-migration.ps1 -PreviewJobId {base._ps_quote(preview_job_id)}",
            operator_input_required=False,
            hfn_migration_required=True,
        )
        return routed

    integration_revision = str(migration.get("integration_bodyrig_revision") or "").strip().lower()
    routed.update(
        rationale=(
            "Historical component continuation is complete and an explicit HFN migration binds the exact promoted package "
            "to its integration revision. Continue the migrated HFN/release status without rewriting historical evidence."
        ),
        next_command=_migration_status_command(
            integration_revision=integration_revision,
            preview_job_id=preview_job_id,
            head=head,
        ),
        operator_input_required=False,
        hfn_migration_required=False,
        hfn_integration_revision=integration_revision,
    )
    return routed


def build_plan(**kwargs: Any) -> dict[str, Any]:
    plan = component.build_plan(**kwargs)
    failed = frozenset(str(value) for value in plan.get("failed_checks") or [])
    if "small_anatomical_detail" in failed:
        return _route_small_detail(plan)
    return plan


def main(argv: list[str] | None = None) -> int:
    args = component.authority.policy._parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
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
        print(component.authority.policy._render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
