from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")


def _fail(message: str) -> None:
    raise ValueError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        _fail(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # pragma: no cover - message path
        _fail(f"{label} is unreadable JSON: {path}: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object: {path}")
    return value


def _need_sha1(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not SHA1_RE.fullmatch(normalized):
        _fail(f"{label} is not an exact Git revision")
    return normalized


def _need_sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(normalized):
        _fail(f"{label} is not a canonical SHA-256")
    return normalized


def _require_boundary(value: dict[str, Any], *, human_recorded: bool | None = None) -> None:
    if value.get("comparison_only") is not True:
        _fail("comparison_only must be true")
    if human_recorded is None:
        if value.get("human_visual_authority_required") is not True:
            _fail("human_visual_authority_required must be true")
    elif human_recorded:
        if value.get("human_visual_authority_recorded") is not True:
            _fail("human_visual_authority_recorded must be true")
    if value.get("physical_acceptance_authority") is not False:
        _fail("physical_acceptance_authority must be false")
    if "promotion_authority" in value and value.get("promotion_authority") is not False:
        _fail("promotion_authority must be false")
    if value.get("production_activation") is not False:
        _fail("production_activation must be false")


def _canonical_run_root(local_app_data: Path) -> Path:
    return (local_app_data / "BodyRig" / "pbr-ab-body-job").resolve()


def _resolve_run_dir(local_app_data: Path, baseline_job_id: str, explicit: str | None) -> Path:
    root = _canonical_run_root(local_app_data)
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            _fail(f"PBR run directory must be under canonical root {root}: {candidate}")
        if not candidate.is_dir():
            _fail(f"PBR run directory not found: {candidate}")
        if not candidate.name.startswith(f"{baseline_job_id}-"):
            _fail("PBR run directory name does not match the baseline job")
        return candidate

    if not root.is_dir():
        _fail(f"canonical PBR run root not found: {root}")
    reviewed = sorted(
        path.resolve()
        for path in root.glob(f"{baseline_job_id}-*")
        if path.is_dir() and (path / "plan-bound-human-review-authority.json").is_file()
    )
    if len(reviewed) != 1:
        _fail(
            "expected exactly one reviewed PBR run for baseline "
            f"{baseline_job_id}, found {len(reviewed)}; pass --pbr-run-dir explicitly"
        )
    return reviewed[0]


def validate(
    *,
    repo_root: Path,
    baseline_job_id: str,
    local_app_data: Path,
    pbr_run_dir: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    local_app_data = local_app_data.resolve()
    if not (repo_root / ".git").is_dir():
        _fail(f"repo root is not a Git checkout: {repo_root}")

    plan_path = local_app_data / "BodyRig" / "ab-baseline-plans" / f"{baseline_job_id}.json"
    plan = _read_json(plan_path, "shared A/B baseline plan")
    if plan.get("format") != "bodyrig-dual-candidate-ab-baseline-plan" or plan.get("version") != 1:
        _fail("shared A/B baseline plan format/version mismatch")
    _require_boundary(plan)
    if plan.get("baseline_job_id") != baseline_job_id:
        _fail("shared A/B baseline plan job identity mismatch")
    person_id = str(plan.get("person_id") or "")
    if not PERSON_RE.fullmatch(person_id):
        _fail("shared A/B baseline plan Person identity is invalid")
    main_revision = _need_sha1(plan.get("baseline_bodyrig_revision"), "baseline revision")
    contract_sha = _need_sha256(plan.get("candidate_contract_sha256"), "candidate contract SHA")

    pbr = plan.get("pbr_candidate")
    throughput = plan.get("throughput_candidate")
    if not isinstance(pbr, dict) or not isinstance(throughput, dict):
        _fail("shared A/B baseline plan candidate identities are missing")
    pbr_ref = str(pbr.get("ref") or "")
    throughput_ref = str(throughput.get("ref") or "")
    if not pbr_ref or not throughput_ref:
        _fail("shared A/B baseline plan candidate refs are missing")
    pbr_revision = _need_sha1(pbr.get("revision"), "PBR candidate revision")
    throughput_revision = _need_sha1(throughput.get("revision"), "throughput candidate revision")

    contract_path = repo_root / "contracts" / "ab-baseline-candidates-v1.json"
    if _sha256(contract_path) != contract_sha:
        _fail("candidate byte contract bytes differ from shared A/B baseline plan")

    run_dir = _resolve_run_dir(local_app_data, baseline_job_id, pbr_run_dir)
    paths = {
        "human_authority": run_dir / "plan-bound-human-review-authority.json",
        "run_authority": run_dir / "run-authority.json",
        "source_authority": run_dir / "body-job-source-authority.json",
        "plan_authority": run_dir / "body-job-plan-authority.json",
        "machine_ab": run_dir / "machine-ab.json",
        "human_review": run_dir / "human-review.json",
    }
    values = {name: _read_json(path, name.replace("_", " ")) for name, path in paths.items()}
    authority = values["human_authority"]
    if authority.get("format") != "bodyrig-pbr-plan-bound-human-review-authority" or authority.get("version") != 1:
        _fail("PBR human-review authority format/version mismatch")
    _require_boundary(authority, human_recorded=True)
    expected_identity = {
        "baseline_job_id": baseline_job_id,
        "person_id": person_id,
        "baseline_plan_sha256": _sha256(plan_path),
        "candidate_contract_sha256": contract_sha,
        "baseline_revision": main_revision,
        "pbr_candidate_ref": pbr_ref,
        "pbr_candidate_revision": pbr_revision,
        "throughput_candidate_ref": throughput_ref,
        "throughput_candidate_revision": throughput_revision,
    }
    for field, expected in expected_identity.items():
        actual = str(authority.get(field) or "")
        if actual != expected:
            _fail(f"PBR human-review authority {field} mismatch")

    receipt_hash_fields = {
        "run_authority_sha256": "run_authority",
        "source_authority_sha256": "source_authority",
        "plan_authority_sha256": "plan_authority",
        "machine_ab_sha256": "machine_ab",
        "human_review_sha256": "human_review",
    }
    for field, key in receipt_hash_fields.items():
        claimed = _need_sha256(authority.get(field), field)
        actual = _sha256(paths[key])
        if claimed != actual:
            _fail(f"PBR human-review authority no longer binds exact {key} bytes")

    plan_authority = values["plan_authority"]
    if plan_authority.get("format") != "bodyrig-pbr-ab-body-job-plan-authority" or plan_authority.get("version") != 1:
        _fail("PBR plan authority format/version mismatch")
    _require_boundary(plan_authority)
    plan_fields = {
        "baseline_plan_sha256": expected_identity["baseline_plan_sha256"],
        "candidate_contract_sha256": contract_sha,
        "baseline_job_id": baseline_job_id,
        "person_id": person_id,
        "baseline_revision": main_revision,
        "pbr_candidate_ref": pbr_ref,
        "pbr_candidate_revision": pbr_revision,
        "throughput_candidate_ref": throughput_ref,
        "throughput_candidate_revision": throughput_revision,
        "run_authority_sha256": _sha256(paths["run_authority"]),
        "source_authority_sha256": _sha256(paths["source_authority"]),
    }
    for field, expected in plan_fields.items():
        if str(plan_authority.get(field) or "") != expected:
            _fail(f"PBR plan authority {field} mismatch")

    source_authority = values["source_authority"]
    if source_authority.get("format") != "bodyrig-pbr-ab-body-job-source-authority" or source_authority.get("version") != 1:
        _fail("PBR source authority format/version mismatch")
    if source_authority.get("comparison_only") is not True or source_authority.get("human_visual_authority_required") is not True:
        _fail("PBR source authority crossed comparison boundary")
    if source_authority.get("physical_acceptance_authority") is not False or source_authority.get("production_activation") is not False:
        _fail("PBR source authority crossed physical/production boundary")
    for field, expected in {
        "body_job_id": baseline_job_id,
        "person_id": person_id,
        "bodyrig_revision": main_revision,
    }.items():
        if str(source_authority.get(field) or "") != expected:
            _fail(f"PBR source authority {field} mismatch")
    stash_performer_id = str(source_authority.get("stash_performer_id") or "").strip()
    if not stash_performer_id:
        _fail("PBR source authority has no revision-bound Stash performer identity")

    run_authority = values["run_authority"]
    if run_authority.get("format") != "bodyrig-pbr-ab-run" or run_authority.get("version") != 1:
        _fail("PBR run authority format/version mismatch")
    if run_authority.get("comparison_only") is not True or run_authority.get("physical_acceptance_authority") is not False:
        _fail("PBR run authority crossed comparison/physical boundary")
    if run_authority.get("production_activation") is not False:
        _fail("PBR run authority crossed production boundary")

    review = values["human_review"]
    if review.get("format") != "bodyrig-fidelity-ab-human-review" or review.get("version") != 1:
        _fail("PBR human-review receipt format/version mismatch")
    if str(review.get("decision") or "") != str(authority.get("decision") or ""):
        _fail("PBR human-review decision does not match terminal authority")
    if review.get("clean_appearance_ab_verified") is not True or review.get("human_visual_review_confirmed") is not True:
        _fail("PBR human-review receipt does not prove explicit four-view visual review")
    if review.get("comparison_only") is not True or review.get("physical_acceptance_authority") is not False or review.get("production_activation") is not False:
        _fail("PBR human-review receipt crossed authority boundary")
    if _need_sha1(review.get("renderer_revision"), "review renderer revision") != main_revision:
        _fail("PBR human-review renderer revision mismatch")
    if _need_sha1(review.get("review_bodyrig_revision"), "review checkout revision") != main_revision:
        _fail("PBR human-review checkout revision mismatch")
    left = review.get("left")
    right = review.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        _fail("PBR human-review left/right identity is missing")
    if _need_sha1(left.get("builder_revision"), "baseline builder revision") != main_revision:
        _fail("PBR human-review baseline builder revision mismatch")
    if _need_sha1(right.get("builder_revision"), "candidate builder revision") != pbr_revision:
        _fail("PBR human-review candidate builder revision mismatch")
    if _need_sha256(review.get("ab_evidence_sha256"), "human-review machine A/B SHA") != _sha256(paths["machine_ab"]):
        _fail("PBR human-review receipt no longer binds exact machine A/B bytes")

    stable_hashes = {name: _sha256(path) for name, path in sorted(paths.items())}
    fingerprint = hashlib.sha256(
        json.dumps(stable_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "format": "bodyrig-pbr-human-review-gate-context",
        "version": 1,
        "baseline_job_id": baseline_job_id,
        "person_id": person_id,
        "stash_performer_id": stash_performer_id,
        "baseline_plan_sha256": expected_identity["baseline_plan_sha256"],
        "candidate_contract_sha256": contract_sha,
        "baseline_revision": main_revision,
        "pbr_candidate_ref": pbr_ref,
        "pbr_candidate_revision": pbr_revision,
        "throughput_candidate_ref": throughput_ref,
        "throughput_candidate_revision": throughput_revision,
        "pbr_run_dir": str(run_dir),
        "pbr_human_review_authority_sha256": stable_hashes["human_authority"],
        "pbr_human_review_sha256": stable_hashes["human_review"],
        "pbr_decision": str(authority.get("decision") or ""),
        "stable_evidence_fingerprint_sha256": fingerprint,
        "comparison_only": True,
        "human_visual_authority_recorded": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate plan-bound PBR human-review authority before throughput sequencing")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--baseline-job-id", required=True)
    parser.add_argument("--pbr-run-dir", default="")
    parser.add_argument("--local-app-data", default=os.environ.get("LOCALAPPDATA", ""))
    args = parser.parse_args()
    if not re.fullmatch(r"job-[0-9a-f]{32}", args.baseline_job_id):
        parser.error("--baseline-job-id must be a canonical BodyRig job id")
    if not args.local_app_data:
        parser.error("LOCALAPPDATA or --local-app-data is required")
    result = validate(
        repo_root=Path(args.repo_root),
        baseline_job_id=args.baseline_job_id,
        local_app_data=Path(args.local_app_data),
        pbr_run_dir=args.pbr_run_dir or None,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
