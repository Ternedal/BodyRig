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


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    local = tmp_path / "local"
    contract = repo / "contracts" / "ab-baseline-candidates-v1.json"
    _write(contract, {"fixture": True})
    contract_sha = _sha(contract)

    plan_path = local / "BodyRig" / "ab-baseline-plans" / f"{JOB}.json"
    _write(
        plan_path,
        {
            "format": "bodyrig-dual-candidate-ab-baseline-plan",
            "version": 1,
            "baseline_job_id": JOB,
            "person_id": PERSON,
            "baseline_bodyrig_revision": MAIN,
            "candidate_contract_sha256": contract_sha,
            "pbr_candidate": {
                "ref": PBR_REF,
                "revision": PBR,
                "retained_reconstruction_reuse": True,
            },
            "throughput_candidate": {
                "ref": THROUGHPUT_REF,
                "revision": THROUGHPUT,
                "separate_candidate_body_build_required": True,
            },
            "ab_baseline_retention": {
                "format": "bodyrig-ab-baseline-retention",
                "version": 1,
                "retain_private_workspace": True,
                "expected_bodyrig_revision": MAIN,
                "job_id": JOB,
            },
            "comparison_only": True,
            "human_visual_authority_required": True,
            "physical_acceptance_authority": False,
            "promotion_authority": False,
            "production_activation": False,
        },
    )

    run = local / "BodyRig" / "pbr-ab-body-job" / f"{JOB}-20260909-000000-deadbeef"
    run.mkdir(parents=True)
    run_authority = run / "run-authority.json"
    source_authority = run / "body-job-source-authority.json"
    machine = run / "machine-ab.json"
    review = run / "human-review.json"
    plan_authority = run / "body-job-plan-authority.json"
    human_authority = run / "plan-bound-human-review-authority.json"

    _write(
        run_authority,
        {
            "format": "bodyrig-pbr-ab-run",
            "version": 1,
            "comparison_only": True,
            "physical_acceptance_authority": False,
            "production_activation": False,
        },
    )
    _write(
        source_authority,
        {
            "format": "bodyrig-pbr-ab-body-job-source-authority",
            "version": 1,
            "body_job_id": JOB,
            "person_id": PERSON,
            "bodyrig_revision": MAIN,
            "stash_performer_id": STASH_PERFORMER,
            "comparison_only": True,
            "human_visual_authority_required": True,
            "physical_acceptance_authority": False,
            "production_activation": False,
        },
    )
    _write(machine, {"format": "fixture-machine-ab", "version": 1})
    _write(
        plan_authority,
        {
            "format": "bodyrig-pbr-ab-body-job-plan-authority",
            "version": 1,
            "baseline_plan_sha256": _sha(plan_path),
            "candidate_contract_sha256": contract_sha,
            "baseline_job_id": JOB,
            "person_id": PERSON,
            "baseline_revision": MAIN,
            "pbr_candidate_ref": PBR_REF,
            "pbr_candidate_revision": PBR,
            "throughput_candidate_ref": THROUGHPUT_REF,
            "throughput_candidate_revision": THROUGHPUT,
            "run_authority_sha256": _sha(run_authority),
            "source_authority_sha256": _sha(source_authority),
            "comparison_only": True,
            "human_visual_authority_required": True,
            "physical_acceptance_authority": False,
            "promotion_authority": False,
            "production_activation": False,
        },
    )
    _write(
        review,
        {
            "format": "bodyrig-fidelity-ab-human-review",
            "version": 1,
            "decision": "right",
            "quality_note": "candidate preserves identity and improves material response",
            "ab_evidence_sha256": _sha(machine),
            "renderer_revision": MAIN,
            "review_bodyrig_revision": MAIN,
            "left": {"builder_revision": MAIN},
            "right": {"builder_revision": PBR},
            "clean_appearance_ab_verified": True,
            "human_visual_review_confirmed": True,
            "comparison_only": True,
            "physical_acceptance_authority": False,
            "production_activation": False,
        },
    )
    _write(
        human_authority,
        {
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
            "run_authority_sha256": _sha(run_authority),
            "source_authority_sha256": _sha(source_authority),
            "plan_authority_sha256": _sha(plan_authority),
            "machine_ab_sha256": _sha(machine),
            "human_review_sha256": _sha(review),
            "decision": "right",
            "comparison_only": True,
            "human_visual_authority_recorded": True,
            "physical_acceptance_authority": False,
            "promotion_authority": False,
            "production_activation": False,
        },
    )
    return repo, local, run, plan_path


def _paths(run: Path, plan_path: Path) -> dict[str, Path]:
    return {
        "plan": plan_path,
        "human_authority": run / "plan-bound-human-review-authority.json",
        "plan_authority": run / "body-job-plan-authority.json",
        "source_authority": run / "body-job-source-authority.json",
        "run_authority": run / "run-authority.json",
        "human_review": run / "human-review.json",
        "machine_ab": run / "machine-ab.json",
    }


def _rebind_chain(run: Path, plan_path: Path) -> None:
    paths = _paths(run, plan_path)
    plan_authority = _read(paths["plan_authority"])
    plan_authority["baseline_plan_sha256"] = _sha(paths["plan"])
    plan_authority["run_authority_sha256"] = _sha(paths["run_authority"])
    plan_authority["source_authority_sha256"] = _sha(paths["source_authority"])
    _write(paths["plan_authority"], plan_authority)

    human_authority = _read(paths["human_authority"])
    human_authority["baseline_plan_sha256"] = _sha(paths["plan"])
    human_authority["run_authority_sha256"] = _sha(paths["run_authority"])
    human_authority["source_authority_sha256"] = _sha(paths["source_authority"])
    human_authority["plan_authority_sha256"] = _sha(paths["plan_authority"])
    human_authority["machine_ab_sha256"] = _sha(paths["machine_ab"])
    human_authority["human_review_sha256"] = _sha(paths["human_review"])
    _write(paths["human_authority"], human_authority)


def _set_version(path: Path, version: object) -> None:
    value = _read(path)
    value["version"] = version
    _write(path, value)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("plan", "shared A/B baseline plan format/version mismatch"),
        ("human_authority", "PBR human-review authority format/version mismatch"),
        ("plan_authority", "PBR plan authority format/version mismatch"),
        ("source_authority", "PBR source authority format/version mismatch"),
        ("run_authority", "PBR run authority format/version mismatch"),
        ("human_review", "PBR human-review receipt format/version mismatch"),
    ],
)
def test_validate_rejects_boolean_versions_at_each_persisted_v1_boundary(
    tmp_path: Path,
    target: str,
    message: str,
) -> None:
    repo, local, run, plan_path = _fixture(tmp_path)
    paths = _paths(run, plan_path)
    _set_version(paths[target], True)
    _rebind_chain(run, plan_path)

    with pytest.raises(ValueError, match=message):
        validate(
            repo_root=repo,
            baseline_job_id=JOB,
            local_app_data=local,
            pbr_run_dir=str(run),
        )


def test_validate_preserves_numeric_float_v1_across_full_hash_bound_chain(tmp_path: Path) -> None:
    repo, local, run, plan_path = _fixture(tmp_path)
    paths = _paths(run, plan_path)
    for target in (
        "plan",
        "human_authority",
        "plan_authority",
        "source_authority",
        "run_authority",
        "human_review",
    ):
        _set_version(paths[target], 1.0)
    _rebind_chain(run, plan_path)

    result = validate(
        repo_root=repo,
        baseline_job_id=JOB,
        local_app_data=local,
        pbr_run_dir=str(run),
    )

    assert result["format"] == "bodyrig-pbr-human-review-gate-context"
    assert result["version"] == 1
    assert result["baseline_job_id"] == JOB
    assert result["stash_performer_id"] == STASH_PERFORMER
    assert result["pbr_decision"] == "right"
    assert result["comparison_only"] is True
    assert result["human_visual_authority_recorded"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False
