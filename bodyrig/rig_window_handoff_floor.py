from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import rig_window_component_authority as component
from .physical_handoff_floor import MINIMUM_PHYSICAL_HANDOFF_REVISION


_PATCH_LOCK = threading.RLock()
_ORIGINAL_ENFORCE_EXISTING_AUTHORITY = component.authority.enforce_existing_authority
_PHYSICAL_EVIDENCE_KINDS = frozenset({"ui-acceptance", "physical-session"})


def _revision_meets_current_handoff_floor(repo_root: Path, revision: str) -> bool:
    revision = str(revision or "").strip().lower()
    base = component.authority.policy.base
    if not base.SHA40.fullmatch(revision):
        return False
    floor = MINIMUM_PHYSICAL_HANDOFF_REVISION
    anchor = base._git(repo_root, "cat-file", "-e", f"{floor}^{{commit}}")
    if anchor.returncode != 0:
        return False
    candidate = base._git(repo_root, "cat-file", "-e", f"{revision}^{{commit}}")
    if candidate.returncode != 0:
        return False
    ancestry = base._git(repo_root, "merge-base", "--is-ancestor", floor, revision)
    return ancestry.returncode == 0


def enforce_existing_authority(
    *,
    repo_root: Path,
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    kept, rejected_out = _ORIGINAL_ENFORCE_EXISTING_AUTHORITY(
        repo_root=repo_root,
        candidates=candidates,
        rejected=rejected,
    )
    head = component.authority.policy.base._head(repo_root)
    filtered: list[dict[str, Any]] = []
    for candidate in kept:
        kind = str(candidate.get("kind") or "")
        revision = str(candidate.get("evidence_revision") or "").strip().lower()
        if (
            kind in _PHYSICAL_EVIDENCE_KINDS
            and revision
            and revision != head
            and not _revision_meets_current_handoff_floor(repo_root, revision)
        ):
            label = str(
                candidate.get("acceptance_dir")
                or candidate.get("session_report")
                or "historical physical evidence"
            )
            rejected_out.append(
                {
                    "evidence": label,
                    "reason": (
                        f"historical physical evidence revision {revision} predates the current minimum physical "
                        f"handoff revision {MINIMUM_PHYSICAL_HANDOFF_REVISION}; it cannot prove the current "
                        "HFN fingernail-geometry/runtime contract"
                    ),
                }
            )
            continue
        filtered.append(candidate)
    return filtered, rejected_out


@contextmanager
def _handoff_floor_guard() -> Iterator[None]:
    with _PATCH_LOCK:
        authority = component.authority
        previous = authority.enforce_existing_authority
        authority.enforce_existing_authority = enforce_existing_authority
        try:
            yield
        finally:
            authority.enforce_existing_authority = previous


def build_plan(**kwargs: Any) -> dict[str, Any]:
    with _handoff_floor_guard():
        return component.build_plan(**kwargs)


def main(argv: list[str] | None = None) -> int:
    policy = component.authority.policy
    args = policy._parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
        return 2
    if args.preferred_job_id and not policy.base.JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    if args.person_id and not policy.base.PERSON_ID.fullmatch(args.person_id):
        print("BodyRig rig-window plan: ERROR | person id is invalid.", file=sys.stderr)
        return 2
    try:
        plan = build_plan(
            repo_root=Path(args.repo_root),
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
        print(policy._render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
