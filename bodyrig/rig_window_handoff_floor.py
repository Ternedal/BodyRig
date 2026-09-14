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
_ORIGINAL_RESCUE_CANDIDATES = component.authority.policy._rescue_candidates
_ORIGINAL_INTERRUPTED_CANDIDATES = component.authority.policy._interrupted_candidates
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


def _floor_reason(*, label: str, revision: str) -> dict[str, str]:
    return {
        "evidence": label,
        "reason": (
            f"historical physical evidence revision {revision or '<unproven>'} predates or cannot prove the current "
            f"minimum physical handoff revision {MINIMUM_PHYSICAL_HANDOFF_REVISION}; it cannot prove the current "
            "drawable hair/eye + complete component visibility + adaptive short-hair-v2 contract"
        ),
    }


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
            rejected_out.append(_floor_reason(label=label, revision=revision))
            continue
        filtered.append(candidate)
    return filtered, rejected_out


def _filter_rescue_candidates(
    repo_root: Path,
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    head = component.authority.policy.base._head(repo_root)
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        revision = str(candidate.get("evidence_revision") or "").strip().lower()
        if revision != head and not _revision_meets_current_handoff_floor(repo_root, revision):
            rejected.append(
                {
                    "job_id": str(candidate.get("job_id") or ""),
                    "reason": _floor_reason(label="historical Gate A rescue", revision=revision)["reason"],
                }
            )
            continue
        filtered.append(candidate)
    return filtered, rejected


def _filter_interrupted_candidates(
    repo_root: Path,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    head = component.authority.policy.base._head(repo_root)
    revisions = {
        str(row.get("job_id") or ""): str(row.get("bodyrig_revision") or "").strip().lower()
        for row in rows
    }
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        job_id = str(candidate.get("job_id") or "")
        revision = revisions.get(job_id, "")
        if revision != head and not _revision_meets_current_handoff_floor(repo_root, revision):
            rejected.append(
                {
                    "job_id": job_id,
                    "reason": _floor_reason(label="historical interrupted recovery", revision=revision)["reason"],
                }
            )
            continue
        filtered.append(candidate)
    return filtered, rejected


@contextmanager
def _handoff_floor_guard(repo_root: Path) -> Iterator[None]:
    root = Path(repo_root).expanduser().resolve()
    with _PATCH_LOCK:
        authority = component.authority
        policy = authority.policy
        previous_existing = authority.enforce_existing_authority
        previous_rescue = policy._rescue_candidates
        previous_interrupted = policy._interrupted_candidates

        def guarded_rescue(
            rows: list[dict[str, Any]],
            *,
            preferred_job_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
            candidates, rejected = _ORIGINAL_RESCUE_CANDIDATES(
                rows,
                preferred_job_id=preferred_job_id,
            )
            return _filter_rescue_candidates(root, candidates, rejected)

        def guarded_interrupted(
            candidate_root: Path,
            rows: list[dict[str, Any]],
            *,
            preferred_job_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
            candidates, rejected = _ORIGINAL_INTERRUPTED_CANDIDATES(
                candidate_root,
                rows,
                preferred_job_id=preferred_job_id,
            )
            return _filter_interrupted_candidates(root, rows, candidates, rejected)

        authority.enforce_existing_authority = enforce_existing_authority
        policy._rescue_candidates = guarded_rescue
        policy._interrupted_candidates = guarded_interrupted
        try:
            yield
        finally:
            authority.enforce_existing_authority = previous_existing
            policy._rescue_candidates = previous_rescue
            policy._interrupted_candidates = previous_interrupted


def build_plan(**kwargs: Any) -> dict[str, Any]:
    repo_root = Path(kwargs["repo_root"]).expanduser().resolve()
    with _handoff_floor_guard(repo_root):
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