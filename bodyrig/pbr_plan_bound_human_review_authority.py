from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


FORMAT = "bodyrig-pbr-human-review-prerequisite"
VERSION = 1
_JOB_RE = re.compile(r"^job-[0-9a-f]{32}$")
_PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PbrHumanReviewAuthorityError(ValueError):
    pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PbrHumanReviewAuthorityError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PbrHumanReviewAuthorityError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PbrHumanReviewAuthorityError(f"{label} must be a JSON object")
    return value


def _sha256_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise PbrHumanReviewAuthorityError(f"{label} is missing: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PbrHumanReviewAuthorityError(f"{label} is unreadable: {path}") from exc
    return digest.hexdigest()


def _revision(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA40_RE.fullmatch(text) is None:
        raise PbrHumanReviewAuthorityError(f"{label} is not an exact Git revision")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise PbrHumanReviewAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _require_boundary(value: dict[str, Any], *, human_recorded: bool, label: str) -> None:
    if value.get("comparison_only") is not True:
        raise PbrHumanReviewAuthorityError(f"{label} is not comparison-only")
    if value.get("physical_acceptance_authority") is not False:
        raise PbrHumanReviewAuthorityError(f"{label} claims physical acceptance authority")
    if value.get("production_activation") is not False:
        raise PbrHumanReviewAuthorityError(f"{label} claims production activation")
    if "promotion_authority" in value and value.get("promotion_authority") is not False:
        raise PbrHumanReviewAuthorityError(f"{label} claims promotion authority")
    if human_recorded and value.get("human_visual_authority_recorded") is not True:
        raise PbrHumanReviewAuthorityError(f"{label} does not record explicit human visual authority")


def inspect_pbr_human_review_prerequisite(
    *,
    baseline_job_id: str,
    run_dir: str | Path,
    shared_plan_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    if _JOB_RE.fullmatch(baseline_job_id) is None:
        raise PbrHumanReviewAuthorityError("baseline job id is not canonical")

    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise PbrHumanReviewAuthorityError(f"PBR run directory is missing: {run_root}")
    plan_path = Path(shared_plan_path).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    if not repo.is_dir():
        raise PbrHumanReviewAuthorityError(f"BodyRig repository root is missing: {repo}")

    plan = _read_json(plan_path, "shared A/B baseline plan")
    if plan.get("format") != "bodyrig-dual-candidate-ab-baseline-plan" or plan.get("version") != 1:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan format/version mismatch")
    if plan.get("baseline_job_id") != baseline_job_id:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan belongs to a different baseline job")
    person_id = str(plan.get("person_id") or "").strip()
    if _PERSON_RE.fullmatch(person_id) is None:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan has invalid Person identity")
    main_revision = _revision(plan.get("baseline_bodyrig_revision"), "baseline plan main revision")
    contract_sha = _sha256(plan.get("candidate_contract_sha256"), "baseline plan candidate contract SHA-256")
    pbr = plan.get("pbr_candidate")
    throughput = plan.get("throughput_candidate")
    if not isinstance(pbr, dict) or not isinstance(throughput, dict):
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan candidate identities are missing")
    pbr_ref = str(pbr.get("ref") or "").strip()
    throughput_ref = str(throughput.get("ref") or "").strip()
    if not pbr_ref or not throughput_ref:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan candidate refs are missing")
    pbr_revision = _revision(pbr.get("revision"), "baseline plan PBR revision")
    throughput_revision = _revision(throughput.get("revision"), "baseline plan throughput revision")
    if plan.get("comparison_only") is not True or plan.get("physical_acceptance_authority") is not False:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan crossed the comparison-only boundary")
    if plan.get("promotion_authority") is not False or plan.get("production_activation") is not False:
        raise PbrHumanReviewAuthorityError("shared A/B baseline plan crossed promotion/production boundary")

    plan_sha = _sha256_file(plan_path, "shared A/B baseline plan")
    contract_path = repo / "contracts" / "ab-baseline-candidates-v1.json"
    if _sha256_file(contract_path, "candidate byte contract") != contract_sha:
        raise PbrHumanReviewAuthorityError("candidate byte contract changed from the shared A/B baseline plan")

    authority_path = run_root / "plan-bound-human-review-authority.json"
    review_path = run_root / "human-review.json"
    run_authority_path = run_root / "run-authority.json"
    source_authority_path = run_root / "body-job-source-authority.json"
    plan_authority_path = run_root / "body-job-plan-authority.json"
    machine_path = run_root / "machine-ab.json"

    authority = _read_json(authority_path, "plan-bound PBR human-review authority")
    if authority.get("format") != "bodyrig-pbr-plan-bound-human-review-authority" or authority.get("version") != 1:
        raise PbrHumanReviewAuthorityError("plan-bound PBR human-review authority format/version mismatch")
    _require_boundary(authority, human_recorded=True, label="plan-bound PBR human-review authority")
    if authority.get("baseline_job_id") != baseline_job_id or authority.get("person_id") != person_id:
        raise PbrHumanReviewAuthorityError("PBR human-review authority identity does not match the shared plan")
    if _sha256(authority.get("baseline_plan_sha256"), "PBR authority baseline-plan SHA-256") != plan_sha:
        raise PbrHumanReviewAuthorityError("PBR human-review authority does not bind the exact shared plan")
    if _sha256(authority.get("candidate_contract_sha256"), "PBR authority contract SHA-256") != contract_sha:
        raise PbrHumanReviewAuthorityError("PBR human-review authority does not bind the exact candidate contract")
    if _revision(authority.get("baseline_revision"), "PBR authority baseline revision") != main_revision:
        raise PbrHumanReviewAuthorityError("PBR human-review authority baseline revision mismatch")
    if authority.get("pbr_candidate_ref") != pbr_ref or _revision(authority.get("pbr_candidate_revision"), "PBR authority candidate revision") != pbr_revision:
        raise PbrHumanReviewAuthorityError("PBR human-review authority PBR candidate mismatch")
    if authority.get("throughput_candidate_ref") != throughput_ref or _revision(authority.get("throughput_candidate_revision"), "PBR authority throughput revision") != throughput_revision:
        raise PbrHumanReviewAuthorityError("PBR human-review authority throughput candidate mismatch")

    linked = {
        "run_authority_sha256": (run_authority_path, "PBR run authority"),
        "source_authority_sha256": (source_authority_path, "PBR source authority"),
        "plan_authority_sha256": (plan_authority_path, "PBR plan authority"),
        "machine_ab_sha256": (machine_path, "PBR machine A/B evidence"),
        "human_review_sha256": (review_path, "PBR human review receipt"),
    }
    for field, (path, label) in linked.items():
        claimed = _sha256(authority.get(field), f"PBR authority {field}")
        if _sha256_file(path, label) != claimed:
            raise PbrHumanReviewAuthorityError(f"{label} changed after terminal PBR human-review authority was recorded")

    review = _read_json(review_path, "PBR human review receipt")
    if review.get("format") != "bodyrig-fidelity-ab-human-review" or review.get("version") != 1:
        raise PbrHumanReviewAuthorityError("PBR human review receipt format/version mismatch")
    if review.get("human_visual_review_confirmed") is not True or review.get("clean_appearance_ab_verified") is not True:
        raise PbrHumanReviewAuthorityError("PBR human review receipt does not prove explicit four-view review")
    _require_boundary(review, human_recorded=False, label="PBR human review receipt")
    if str(review.get("decision") or "") != str(authority.get("decision") or ""):
        raise PbrHumanReviewAuthorityError("PBR human review decision differs from terminal authority")
    if _revision(review.get("renderer_revision"), "PBR review renderer revision") != main_revision:
        raise PbrHumanReviewAuthorityError("PBR human review renderer revision mismatch")
    if _revision(review.get("review_bodyrig_revision"), "PBR review checkout revision") != main_revision:
        raise PbrHumanReviewAuthorityError("PBR human review checkout revision mismatch")
    left = review.get("left")
    right = review.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise PbrHumanReviewAuthorityError("PBR human review receipt side identities are missing")
    if _revision(left.get("builder_revision"), "PBR review baseline builder revision") != main_revision:
        raise PbrHumanReviewAuthorityError("PBR human review baseline builder revision mismatch")
    if _revision(right.get("builder_revision"), "PBR review candidate builder revision") != pbr_revision:
        raise PbrHumanReviewAuthorityError("PBR human review candidate builder revision mismatch")

    return {
        "format": FORMAT,
        "version": VERSION,
        "baseline_job_id": baseline_job_id,
        "person_id": person_id,
        "baseline_revision": main_revision,
        "pbr_candidate_ref": pbr_ref,
        "pbr_candidate_revision": pbr_revision,
        "throughput_candidate_ref": throughput_ref,
        "throughput_candidate_revision": throughput_revision,
        "baseline_plan_sha256": plan_sha,
        "candidate_contract_sha256": contract_sha,
        "pbr_run_dir": str(run_root),
        "pbr_human_review_authority_sha256": _sha256_file(authority_path, "plan-bound PBR human-review authority"),
        "pbr_human_review_sha256": _sha256_file(review_path, "PBR human review receipt"),
        "decision": str(authority.get("decision") or ""),
        "human_visual_authority_recorded": True,
        "comparison_only": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate plan-bound PBR human review as a throughput prerequisite")
    parser.add_argument("--baseline-job-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--shared-plan", required=True)
    parser.add_argument("--repo-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = inspect_pbr_human_review_prerequisite(
        baseline_job_id=args.baseline_job_id,
        run_dir=args.run_dir,
        shared_plan_path=args.shared_plan,
        repo_root=args.repo_root,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
