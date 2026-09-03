from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .person_source_alignment import file_sha256
from .recovery_throughput_review_bundle import (
    RecoveryThroughputReviewBundleError,
    verify_bundle,
)

FORMAT = "bodyrig-recovery-throughput-human-review"
VERSION = 1
SEMANTICS = "explicit-human-ab-review-not-promotion-authority"
_CRITERIA = (
    "identity_shape",
    "face_identity",
    "skin_texture_alignment",
    "gross_anatomy",
)
_ALLOWED = {"pass", "fail"}


class RecoveryThroughputHumanReviewError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryThroughputHumanReviewError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise RecoveryThroughputHumanReviewError(f"{label} must be a JSON object")
    return value


def _validate_criteria(criteria: Mapping[str, str]) -> dict[str, str]:
    if set(criteria) != set(_CRITERIA):
        raise RecoveryThroughputHumanReviewError("human review criteria set is incomplete or unsupported")
    normalized: dict[str, str] = {}
    for key in _CRITERIA:
        value = str(criteria[key]).strip().lower()
        if value not in _ALLOWED:
            raise RecoveryThroughputHumanReviewError(f"invalid human review result for {key}: {value!r}")
        normalized[key] = value
    return normalized


def record_review(
    bundle_dir: str | Path,
    *,
    out_path: str | Path,
    reviewer: str,
    criteria: Mapping[str, str],
    note: str,
) -> dict[str, Any]:
    bundle_root = Path(bundle_dir).expanduser().resolve()
    bundle = verify_bundle(bundle_root)

    reviewer_value = str(reviewer).strip()
    if not reviewer_value or len(reviewer_value) > 240:
        raise RecoveryThroughputHumanReviewError("reviewer must be 1..240 characters")
    note_value = str(note).strip()
    if not note_value or len(note_value) > 8000:
        raise RecoveryThroughputHumanReviewError("review note must be 1..8000 characters")
    results = _validate_criteria(criteria)

    machine_path = bundle_root / "machine-audit.json"
    machine = _read_json(machine_path, label="machine A/B audit")
    if machine.get("machine_evidence_pass") is not True or machine.get("decision") != "eligible-for-human-ab-review":
        raise RecoveryThroughputHumanReviewError("review bundle machine evidence is not eligible for human A/B review")
    if machine.get("promotion_authority") is not False or machine.get("production_activation") is not False:
        raise RecoveryThroughputHumanReviewError("machine A/B evidence crossed the promotion/production authority boundary")

    passed = all(results[key] == "pass" for key in _CRITERIA)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "semantics": SEMANTICS,
        "created_utc": _now(),
        "reviewer": reviewer_value,
        "person_id": bundle.get("person_id"),
        "baseline_job_id": bundle.get("baseline_job_id"),
        "candidate_job_id": bundle.get("candidate_job_id"),
        "baseline_bodyrig_revision": bundle.get("baseline_bodyrig_revision"),
        "candidate_bodyrig_revision": bundle.get("candidate_bodyrig_revision"),
        "review_bundle_receipt_sha256": file_sha256(bundle_root / "review-bundle.json"),
        "machine_audit_sha256": file_sha256(machine_path),
        "reviewed_views": [dict(item) for item in bundle.get("views", [])],
        "criteria": results,
        "note": note_value,
        "human_visual_review_completed": True,
        "human_visual_review_passed": passed,
        "decision": "no-material-regression" if passed else "material-regression",
        "next_gate": "eligible-for-explicit-promotion-review" if passed else "blocked-material-regression",
        "promotion_authority": False,
        "production_activation": False,
    }

    target = Path(out_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise RecoveryThroughputHumanReviewError(f"refusing to overwrite human A/B review: {target}") from exc
    return receipt


def verify_review(review_path: str | Path, *, bundle_dir: str | Path) -> dict[str, Any]:
    bundle_root = Path(bundle_dir).expanduser().resolve()
    bundle = verify_bundle(bundle_root)
    receipt = _read_json(Path(review_path).expanduser().resolve(), label="human A/B review")
    if receipt.get("format") != FORMAT or receipt.get("version") != VERSION or receipt.get("semantics") != SEMANTICS:
        raise RecoveryThroughputHumanReviewError("human A/B review format/version/semantics mismatch")
    if receipt.get("promotion_authority") is not False or receipt.get("production_activation") is not False:
        raise RecoveryThroughputHumanReviewError("human A/B review cannot carry promotion/production authority")
    if receipt.get("human_visual_review_completed") is not True:
        raise RecoveryThroughputHumanReviewError("human A/B review is not complete")
    results = _validate_criteria(receipt.get("criteria") if isinstance(receipt.get("criteria"), Mapping) else {})
    expected_passed = all(results[key] == "pass" for key in _CRITERIA)
    if receipt.get("human_visual_review_passed") is not expected_passed:
        raise RecoveryThroughputHumanReviewError("human A/B review pass flag does not match criteria")
    expected_decision = "no-material-regression" if expected_passed else "material-regression"
    if receipt.get("decision") != expected_decision:
        raise RecoveryThroughputHumanReviewError("human A/B review decision does not match criteria")
    expected_next = "eligible-for-explicit-promotion-review" if expected_passed else "blocked-material-regression"
    if receipt.get("next_gate") != expected_next:
        raise RecoveryThroughputHumanReviewError("human A/B review next gate does not match criteria")
    if receipt.get("review_bundle_receipt_sha256") != file_sha256(bundle_root / "review-bundle.json"):
        raise RecoveryThroughputHumanReviewError("human A/B review no longer matches review-bundle receipt bytes")
    if receipt.get("machine_audit_sha256") != file_sha256(bundle_root / "machine-audit.json"):
        raise RecoveryThroughputHumanReviewError("human A/B review no longer matches machine-audit bytes")
    for key in (
        "person_id",
        "baseline_job_id",
        "candidate_job_id",
        "baseline_bodyrig_revision",
        "candidate_bodyrig_revision",
    ):
        if receipt.get(key) != bundle.get(key):
            raise RecoveryThroughputHumanReviewError(f"human A/B review {key} no longer matches review bundle")
    if receipt.get("reviewed_views") != bundle.get("views"):
        raise RecoveryThroughputHumanReviewError("human A/B review view hashes no longer match review bundle")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record an explicit create-only human visual A/B review bound to an immutable recovery-throughput review bundle.")
    parser.add_argument("bundle_dir")
    parser.add_argument("--out", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--identity-shape", choices=sorted(_ALLOWED), required=True)
    parser.add_argument("--face-identity", choices=sorted(_ALLOWED), required=True)
    parser.add_argument("--skin-texture-alignment", choices=sorted(_ALLOWED), required=True)
    parser.add_argument("--gross-anatomy", choices=sorted(_ALLOWED), required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    try:
        result = record_review(
            args.bundle_dir,
            out_path=args.out,
            reviewer=args.reviewer,
            criteria={
                "identity_shape": args.identity_shape,
                "face_identity": args.face_identity,
                "skin_texture_alignment": args.skin_texture_alignment,
                "gross_anatomy": args.gross_anatomy,
            },
            note=args.note,
        )
        verify_review(args.out, bundle_dir=args.bundle_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, RecoveryThroughputReviewBundleError, RecoveryThroughputHumanReviewError, ValueError) as exc:
        print(f"BodyRig recovery throughput human review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
