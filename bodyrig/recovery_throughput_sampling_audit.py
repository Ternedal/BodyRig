from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_POLICY
from .recovery_throughput_audit import (
    RecoveryThroughputAuditError,
    RunEvidence,
    _write_create_only,
    collect_run,
    compare_runs,
)


def expected_candidate_revision(baseline_revision: str) -> str:
    baseline = str(baseline_revision or "").strip()
    if not baseline:
        raise RecoveryThroughputAuditError("baseline recovery revision is missing")
    suffix = f";sampling:{RECOVERY_TEMPORAL_SAMPLING_POLICY}"
    if baseline.endswith(suffix):
        raise RecoveryThroughputAuditError("baseline already uses the candidate recovery sampling revision")
    return baseline + suffix


def compare_sampling_runs(baseline: RunEvidence, candidate: RunEvidence) -> dict[str, Any]:
    baseline_revision = str(baseline.recovery.get("revision") or "")
    candidate_revision = str(candidate.recovery.get("revision") or "")
    policy_blockers: list[str] = []

    try:
        expected_revision = expected_candidate_revision(baseline_revision)
    except RecoveryThroughputAuditError as exc:
        expected_revision = ""
        policy_blockers.append(str(exc))

    if expected_revision and candidate_revision != expected_revision:
        policy_blockers.append("candidate recovery revision is not the exact versioned sampling derivative of baseline")

    same_adapter = baseline.recovery.get("adapter") == candidate.recovery.get("adapter")
    same_track = baseline.recovery.get("track_id") == candidate.recovery.get("track_id")
    revision_policy_ok = bool(expected_revision) and candidate_revision == expected_revision

    # The generic audit intentionally requires identical recovery revisions.
    # Normalize only that one field after proving the exact allowed derivative;
    # every source, selection, segment, adapter, track and observed-frame check
    # remains owned by the generic fail-closed comparison.
    normalized_recovery = dict(candidate.recovery)
    normalized_recovery["revision"] = baseline_revision
    normalized_candidate = replace(candidate, recovery=normalized_recovery)
    result = compare_runs(baseline, normalized_candidate)

    blockers = list(result.get("blockers") or [])
    for blocker in policy_blockers:
        if blocker not in blockers:
            blockers.append(blocker)

    machine_pass = bool(result.get("machine_evidence_pass")) and not policy_blockers
    result.update(
        {
            "baseline_recovery_revision": baseline_revision,
            "candidate_recovery_revision": candidate_revision,
            "expected_candidate_recovery_revision": expected_revision,
            "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
            "upstream_recovery_authority_equal": same_adapter and same_track and revision_policy_ok,
            "recovery_authority_equal": same_adapter and same_track and revision_policy_ok,
            "machine_evidence_pass": machine_pass,
            "blockers": blockers,
            "human_visual_review_required": True,
            "promotion_authority": False,
            "production_activation": False,
            "decision": "eligible-for-human-ab-review" if machine_pass else "blocked",
        }
    )
    return result


def audit_sampling_candidate(
    baseline_job: str | Path,
    candidate_job: str | Path,
    *,
    person_root: str | Path | None = None,
) -> dict[str, Any]:
    baseline = collect_run(baseline_job, person_root=person_root)
    candidate = collect_run(candidate_job, person_root=person_root)
    return compare_sampling_runs(baseline, candidate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only A/B audit for the versioned BodyRig PHALP sampling candidate. "
            "Never grants promotion authority."
        )
    )
    parser.add_argument("baseline_job", help="uncapped baseline body-build job directory or job.json")
    parser.add_argument("candidate_job", help="sampling-candidate body-build job directory or job.json")
    parser.add_argument("--person-root", default="", help="optional Person Library root override")
    parser.add_argument("--out", default="", help="optional create-only JSON report")
    args = parser.parse_args(argv)
    try:
        result = audit_sampling_candidate(
            args.baseline_job,
            args.candidate_job,
            person_root=args.person_root or None,
        )
        if args.out:
            _write_create_only(Path(args.out), result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["machine_evidence_pass"] else 1
    except (OSError, RecoveryThroughputAuditError, ValueError) as exc:
        print(f"BodyRig recovery throughput sampling A/B audit: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
