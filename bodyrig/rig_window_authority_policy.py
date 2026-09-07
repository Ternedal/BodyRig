from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import rig_window_policy as policy


COMMITTED_GATE_A_RANK = 16
_PATCH_LOCK = threading.RLock()
_ORIGINAL_EXISTING_CANDIDATES = policy._existing_candidates


def _committed_gate_a(candidate: dict[str, Any]) -> bool:
    """Return True only when Gate A bytes are already persistently committed.

    A completed physical clone session also reports its next gate as ``gate-a``,
    but its prospective acceptance directory does not exist yet. That session
    must remain below a validated Gate-A rescue. A real Gate-A acceptance has a
    persisted ``bodyrig-acceptance.json`` and is farther than a rescue because
    no Gate-A promotion/render step needs to be repeated.
    """

    if str(candidate.get("gate") or "") != "gate-a":
        return False
    acceptance_text = str(candidate.get("acceptance_dir") or "").strip()
    if not acceptance_text:
        return False
    try:
        acceptance_dir = Path(acceptance_text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return (acceptance_dir / "bodyrig-acceptance.json").is_file()


def _strict_complete_historical_revision_is_safe(repo_root: Path, revision: str) -> bool:
    """Require locally fetched origin/main ancestry for terminal evidence.

    Non-terminal historical candidates are guarded again by
    ``update-windows.ps1 -Revision`` before any checkout/service mutation, so
    the legacy planner may defer an unavailable remote-ref proof to that updater.
    A structurally complete candidate has no later checkout command, however;
    accepting it would stop the rig plan immediately. Complete historical
    evidence therefore needs the ancestry proof *now*. Normal update/auto-plan
    has already fetched ``origin/main``, so absence of that ref is a blocker.
    """

    revision = str(revision or "").strip().lower()
    if not policy.base.SHA40.fullmatch(revision):
        return False
    branch = policy.base._git(repo_root, "rev-parse", "refs/remotes/origin/main^{commit}")
    branch_head = branch.stdout.strip().lower()
    if branch.returncode != 0 or not policy.base.SHA40.fullmatch(branch_head):
        return False
    ancestor = policy.base._git(repo_root, "merge-base", "--is-ancestor", revision, branch_head)
    return ancestor.returncode == 0


def enforce_existing_authority(
    *,
    repo_root: Path,
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize existing-evidence rank and remove terminal unsafe history."""

    head = policy.base._head(repo_root)
    kept: list[dict[str, Any]] = []
    rejected_out = list(rejected)

    for raw in candidates:
        candidate = dict(raw)
        if _committed_gate_a(candidate):
            candidate["rank"] = max(int(candidate.get("rank") or 0), COMMITTED_GATE_A_RANK)

        revision = str(candidate.get("evidence_revision") or "").strip().lower()
        if revision and revision != head and str(candidate.get("state") or "") == "complete":
            if not _strict_complete_historical_revision_is_safe(repo_root, revision):
                label = str(candidate.get("acceptance_dir") or candidate.get("session_report") or "historical evidence")
                rejected_out.append(
                    {
                        "evidence": label,
                        "reason": (
                            "complete historical evidence revision is not proven as an ancestor of the locally fetched "
                            "origin/main authority"
                        ),
                    }
                )
                continue
        kept.append(candidate)

    return kept, rejected_out


def _guarded_existing_candidates(
    *,
    repo_root: Path,
    root: Path,
    rows: list[dict[str, Any]],
    performer_id: str,
    resolved_performer: str,
    body_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates, rejected = _ORIGINAL_EXISTING_CANDIDATES(
        repo_root=repo_root,
        root=root,
        rows=rows,
        performer_id=performer_id,
        resolved_performer=resolved_performer,
        body_id=body_id,
    )
    return enforce_existing_authority(
        repo_root=repo_root,
        candidates=candidates,
        rejected=rejected,
    )


@contextmanager
def _authority_guard() -> Iterator[None]:
    """Install the candidate guard only for one planner call.

    ``rig_window_policy`` is also imported directly by tests and tooling, so the
    hardening shim must not permanently mutate its module globals. The planner
    CLI is single-process, but a re-entrant lock also keeps library callers from
    observing a partially installed guard.
    """

    with _PATCH_LOCK:
        previous = policy._existing_candidates
        policy._existing_candidates = _guarded_existing_candidates
        try:
            yield
        finally:
            policy._existing_candidates = previous


def build_plan(**kwargs: Any) -> dict[str, Any]:
    with _authority_guard():
        return policy.build_plan(**kwargs)


def main(argv: list[str] | None = None) -> int:
    with _authority_guard():
        return policy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
