from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.pbr_plan_bound_human_review_authority import (
    PbrHumanReviewAuthorityError,
    inspect_pbr_human_review_prerequisite,
)


MAIN = "1" * 40
PBR = "2" * 40
THROUGHPUT = "3" * 40
JOB = "job-" + "a" * 32
PERSON = "person-" + "b" * 32
PBR_REF = "candidate/skin-pbr-v2-current-main-20260908"
THROUGHPUT_REF = "candidate/recovery-throughput-v3-current-main-20260908"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    run = tmp_path / "pbr-run"
    plan_path = tmp_path / "shared-plan.json"
    contract_path = repo / "contracts" / "ab-baseline-candidates-v1.json"
    _write(contract_path, {"format": "bodyrig-ab-baseline-candidates", "version": 1, "test": True})
    contract_sha = _sha(contract_path)

    plan = {
        "format": "bodyrig-dual-candidate-ab-baseline-plan",
        "version": 1,
        "baseline_job_id": JOB,
        "person_id": PERSON,
        "baseline_bodyrig_revision": MAIN,
        "candidate_contract_sha256": contract_sha,
        "pbr_candidate": {"ref": PBR_REF, "revision": PBR, "retained_reconstruction_reuse": True},
        "throughput_candidate": {"ref": THROUGHPUT_REF, "revision": THROUGHPUT, "separate_candidate_body_build_required": True},
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    _write(plan_path, plan)

    _write(run / "run-authority.json", {"format": "run", "revision": MAIN})
    _write(run / "body-job-source-authority.json", {"format": "source", "job": JOB})
    _write(run / "body-job-plan-authority.json", {"format": "plan", "job": JOB})
    _write(run / "machine-ab.json", {"format": "machine", "baseline": MAIN, "candidate": PBR})
    review = {
        "format": "bodyrig-fidelity-ab-human-review",
        "version": 1,
        "decision": "right",
        "human_visual_review_confirmed": True,
        "clean_appearance_ab_verified": True,
        "renderer_revision": MAIN,
        "review_bodyrig_revision": MAIN,
        "left": {"builder_revision": MAIN},
        "right": {"builder_revision": PBR},
        "comparison_only": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }
    _write(run / "human-review.json", review)

    authority = {
        "format": "bodyrig-pbr-plan-bound-human-review-authority",
        "version": 1,
        "baseline_job_id": JOB,
        "person_id": PERSON,
        "baseline_plan_sha256": _sha(plan_path),
        "candidate_contract_sha256": contract_sha,
        "baseline_revision": MAIN,
        "pbr_candidate_ref": PBR_REF,
        "pbr_candidate_revision": PBR,
        "throughput_candidate_ref": THROUGHPUT_REF,
        "throughput_candidate_revision": THROUGHPUT,
        "run_authority_sha256": _sha(run / "run-authority.json"),
        "source_authority_sha256": _sha(run / "body-job-source-authority.json"),
        "plan_authority_sha256": _sha(run / "body-job-plan-authority.json"),
        "machine_ab_sha256": _sha(run / "machine-ab.json"),
        "human_review_sha256": _sha(run / "human-review.json"),
        "decision": "right",
        "comparison_only": True,
        "human_visual_authority_recorded": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    _write(run / "plan-bound-human-review-authority.json", authority)
    return repo, run, plan_path


def test_prerequisite_binds_exact_plan_review_and_candidate_revisions(tmp_path: Path) -> None:
    repo, run, plan_path = _fixture(tmp_path)
    result = inspect_pbr_human_review_prerequisite(
        baseline_job_id=JOB,
        run_dir=run,
        shared_plan_path=plan_path,
        repo_root=repo,
    )
    assert result["format"] == "bodyrig-pbr-human-review-prerequisite"
    assert result["baseline_job_id"] == JOB
    assert result["person_id"] == PERSON
    assert result["baseline_revision"] == MAIN
    assert result["pbr_candidate_revision"] == PBR
    assert result["throughput_candidate_revision"] == THROUGHPUT
    assert result["human_visual_authority_recorded"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
    assert result["pbr_human_review_authority_sha256"] == _sha(run / "plan-bound-human-review-authority.json")
    assert result["pbr_human_review_sha256"] == _sha(run / "human-review.json")


def test_prerequisite_rejects_human_review_byte_tamper(tmp_path: Path) -> None:
    repo, run, plan_path = _fixture(tmp_path)
    with (run / "human-review.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(PbrHumanReviewAuthorityError, match="human review receipt changed"):
        inspect_pbr_human_review_prerequisite(
            baseline_job_id=JOB,
            run_dir=run,
            shared_plan_path=plan_path,
            repo_root=repo,
        )


def test_prerequisite_rejects_authority_candidate_drift(tmp_path: Path) -> None:
    repo, run, plan_path = _fixture(tmp_path)
    path = run / "plan-bound-human-review-authority.json"
    authority = json.loads(path.read_text(encoding="utf-8"))
    authority["throughput_candidate_revision"] = "4" * 40
    _write(path, authority)
    with pytest.raises(PbrHumanReviewAuthorityError, match="throughput candidate mismatch"):
        inspect_pbr_human_review_prerequisite(
            baseline_job_id=JOB,
            run_dir=run,
            shared_plan_path=plan_path,
            repo_root=repo,
        )


def test_prerequisite_rejects_authority_boundary_escalation(tmp_path: Path) -> None:
    repo, run, plan_path = _fixture(tmp_path)
    path = run / "plan-bound-human-review-authority.json"
    authority = json.loads(path.read_text(encoding="utf-8"))
    authority["promotion_authority"] = True
    _write(path, authority)
    with pytest.raises(PbrHumanReviewAuthorityError, match="promotion authority"):
        inspect_pbr_human_review_prerequisite(
            baseline_job_id=JOB,
            run_dir=run,
            shared_plan_path=plan_path,
            repo_root=repo,
        )
