from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.pbr_human_review_gate import validate


JOB = "job-" + "1" * 32
PERSON = "person-" + "2" * 32
STASH_PERFORMER = "42"
MAIN = "3" * 40
PBR = "4" * 40
THROUGHPUT = "5" * 40
PBR_REF = "candidate/skin-pbr-v3-linear-light-20260909"
THROUGHPUT_REF = "candidate/recovery-throughput-v3-current-main-20260908"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    local = tmp_path / "local"
    contract = repo / "contracts" / "ab-baseline-candidates-v1.json"
    _write(contract, {"fixture": True})
    contract_sha = _sha(contract)

    plan_path = local / "BodyRig" / "ab-baseline-plans" / f"{JOB}.json"
    plan = {
        "format": "bodyrig-dual-candidate-ab-baseline-plan",
        "version": 1,
        "baseline_job_id": JOB,
        "person_id": PERSON,
        "baseline_bodyrig_revision": MAIN,
        "candidate_contract_sha256": contract_sha,
        "pbr_candidate": {"ref": PBR_REF, "revision": PBR, "retained_reconstruction_reuse": True},
        "throughput_candidate": {"ref": THROUGHPUT_REF, "revision": THROUGHPUT, "separate_candidate_body_build_required": True},
        "ab_baseline_retention": {"format": "bodyrig-ab-baseline-retention", "version": 1, "retain_private_workspace": True, "expected_bodyrig_revision": MAIN, "job_id": JOB},
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    _write(plan_path, plan)

    run = local / "BodyRig" / "pbr-ab-body-job" / f"{JOB}-20260909-000000-deadbeef"
    run.mkdir(parents=True)
    run_authority = run / "run-authority.json"
    source_authority = run / "body-job-source-authority.json"
    machine = run / "machine-ab.json"
    review = run / "human-review.json"
    plan_authority = run / "body-job-plan-authority.json"
    human_authority = run / "plan-bound-human-review-authority.json"

    _write(run_authority, {
        "format": "bodyrig-pbr-ab-run", "version": 1,
        "comparison_only": True, "physical_acceptance_authority": False,
        "production_activation": False,
    })
    _write(source_authority, {
        "format": "bodyrig-pbr-ab-body-job-source-authority", "version": 1,
        "body_job_id": JOB, "person_id": PERSON, "bodyrig_revision": MAIN,
        "stash_performer_id": STASH_PERFORMER,
        "comparison_only": True, "human_visual_authority_required": True,
        "physical_acceptance_authority": False, "production_activation": False,
    })
    _write(machine, {"format": "fixture-machine-ab", "version": 1})
    _write(plan_authority, {
        "format": "bodyrig-pbr-ab-body-job-plan-authority", "version": 1,
        "baseline_plan_sha256": _sha(plan_path),
        "candidate_contract_sha256": contract_sha,
        "baseline_job_id": JOB, "person_id": PERSON, "baseline_revision": MAIN,
        "pbr_candidate_ref": PBR_REF, "pbr_candidate_revision": PBR,
        "throughput_candidate_ref": THROUGHPUT_REF, "throughput_candidate_revision": THROUGHPUT,
        "run_authority_sha256": _sha(run_authority), "source_authority_sha256": _sha(source_authority),
        "comparison_only": True, "human_visual_authority_required": True,
        "physical_acceptance_authority": False, "promotion_authority": False,
        "production_activation": False,
    })
    _write(review, {
        "format": "bodyrig-fidelity-ab-human-review", "version": 1,
        "decision": "right", "quality_note": "candidate preserves identity and improves material response",
        "ab_evidence_sha256": _sha(machine), "renderer_revision": MAIN, "review_bodyrig_revision": MAIN,
        "left": {"builder_revision": MAIN}, "right": {"builder_revision": PBR},
        "clean_appearance_ab_verified": True, "human_visual_review_confirmed": True,
        "comparison_only": True, "physical_acceptance_authority": False, "production_activation": False,
    })
    _write(human_authority, {
        "format": "bodyrig-pbr-plan-bound-human-review-authority", "version": 1,
        "baseline_job_id": JOB, "person_id": PERSON, "baseline_plan_sha256": _sha(plan_path),
        "candidate_contract_sha256": contract_sha, "baseline_revision": MAIN,
        "pbr_candidate_ref": PBR_REF, "pbr_candidate_revision": PBR,
        "throughput_candidate_ref": THROUGHPUT_REF, "throughput_candidate_revision": THROUGHPUT,
        "run_authority_sha256": _sha(run_authority), "source_authority_sha256": _sha(source_authority),
        "plan_authority_sha256": _sha(plan_authority), "machine_ab_sha256": _sha(machine),
        "human_review_sha256": _sha(review), "decision": "right",
        "comparison_only": True, "human_visual_authority_recorded": True,
        "physical_acceptance_authority": False, "promotion_authority": False,
        "production_activation": False,
    })
    return repo, local, run


def test_validate_binds_exact_pbr_human_review_chain(tmp_path: Path) -> None:
    repo, local, run = _fixture(tmp_path)
    result = validate(repo_root=repo, baseline_job_id=JOB, local_app_data=local, pbr_run_dir=str(run))
    assert result["format"] == "bodyrig-pbr-human-review-gate-context"
    assert result["baseline_job_id"] == JOB
    assert result["stash_performer_id"] == STASH_PERFORMER
    assert result["pbr_candidate_revision"] == PBR
    assert result["throughput_candidate_revision"] == THROUGHPUT
    assert result["pbr_decision"] == "right"
    assert result["human_visual_authority_recorded"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False


def test_validate_rejects_missing_source_performer_authority(tmp_path: Path) -> None:
    repo, local, run = _fixture(tmp_path)
    source_path = run / "body-job-source-authority.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source.pop("stash_performer_id")
    _write(source_path, source)
    plan_authority_path = run / "body-job-plan-authority.json"
    plan_authority = json.loads(plan_authority_path.read_text(encoding="utf-8"))
    plan_authority["source_authority_sha256"] = _sha(source_path)
    _write(plan_authority_path, plan_authority)
    human_authority_path = run / "plan-bound-human-review-authority.json"
    human_authority = json.loads(human_authority_path.read_text(encoding="utf-8"))
    human_authority["source_authority_sha256"] = _sha(source_path)
    human_authority["plan_authority_sha256"] = _sha(plan_authority_path)
    _write(human_authority_path, human_authority)
    with pytest.raises(ValueError, match="no revision-bound Stash performer identity"):
        validate(repo_root=repo, baseline_job_id=JOB, local_app_data=local, pbr_run_dir=str(run))


def test_validate_rejects_human_review_tamper(tmp_path: Path) -> None:
    repo, local, run = _fixture(tmp_path)
    review_path = run / "human-review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["decision"] = "left"
    _write(review_path, review)
    with pytest.raises(ValueError, match="human_review bytes|human-review"):
        validate(repo_root=repo, baseline_job_id=JOB, local_app_data=local, pbr_run_dir=str(run))


def test_validate_requires_unambiguous_reviewed_run_when_not_explicit(tmp_path: Path) -> None:
    repo, local, run = _fixture(tmp_path)
    duplicate = run.parent / f"{JOB}-20260909-000001-cafebabe"
    duplicate.mkdir(parents=True)
    (duplicate / "plan-bound-human-review-authority.json").write_bytes((run / "plan-bound-human-review-authority.json").read_bytes())
    with pytest.raises(ValueError, match="expected exactly one reviewed PBR run"):
        validate(repo_root=repo, baseline_job_id=JOB, local_app_data=local)
