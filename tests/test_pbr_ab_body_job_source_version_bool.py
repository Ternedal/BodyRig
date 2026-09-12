from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.pbr_ab_body_job_source as source


REVISION = "a" * 40
FLOOR = "9" * 40
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
STASH_PERFORMER_ID = "42"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _git_ok(_repo: Path, *args: str) -> str:
    if args == ("rev-parse", "HEAD"):
        return REVISION
    if args == ("rev-parse", "refs/remotes/origin/main"):
        return REVISION
    if args[0:2] == ("cat-file", "-e"):
        return ""
    if args == ("merge-base", "--is-ancestor", FLOOR, REVISION):
        return ""
    raise AssertionError(f"unexpected git call: {args}")


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict, Path, dict]:
    repo = tmp_path / "repo"
    job_root = tmp_path / "job-root"
    clone_output = job_root / "clone-output"
    acceptance = job_root / "acceptance"
    fidelity = job_root / "fidelity-review"
    workspace = tmp_path / "workspace"
    sith_input = workspace / "sith-input-v1"

    for directory in (clone_output, acceptance, fidelity, sith_input):
        directory.mkdir(parents=True, exist_ok=True)
    (clone_output / "bodyrig-sith-fitter-config.json").write_text("{}\n", encoding="utf-8")
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")
    (job_root / "job.log").write_text("fixture\n", encoding="utf-8")
    (sith_input / "reconstruction.json").write_text("{}\n", encoding="utf-8")
    (sith_input / "reconstruction-authority.json").write_text("{}\n", encoding="utf-8")

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "succeeded",
        "bodyrig_revision": REVISION,
        "source_enqueue_authority": {
            "format": "bodyrig-body-build-source-enqueue-authority",
            "version": 1,
            "job_id": JOB_ID,
            "person_id": PERSON_ID,
            "stash_performer_id": STASH_PERFORMER_ID,
            "expected_bodyrig_revision": REVISION,
        },
        "session_report": str(job_root / "physical-session.json"),
        "clone_output": str(clone_output),
        "acceptance_dir": str(acceptance),
        "fidelity_dir": str(fidelity),
        "log_path": str(job_root / "job.log"),
        "body_revision": "body-r0001",
        "canonical_body_id": "canonical-body",
        "source_binding_sha256": "b" * 64,
        "body_review_sha256": "c" * 64,
        "ab_baseline_retention": {
            "format": "bodyrig-ab-baseline-retention",
            "version": 1,
            "retain_private_workspace": True,
            "expected_bodyrig_revision": REVISION,
            "job_id": JOB_ID,
        },
    }
    job_path = job_root / "job.json"
    _write_json(job_path, job)

    policy = {
        "format": "bodyrig-pbr-ab-source-policy",
        "version": 1,
        "safe_source_floor_revision": FLOOR,
    }
    policy_path = repo / "contracts" / "pbr-ab-source-policy-v1.json"
    _write_json(policy_path, policy)

    monkeypatch.setattr(source, "_git", _git_ok)
    monkeypatch.setattr(source, "_canonical_job_path", lambda _job_id: job_path)
    monkeypatch.setattr(source, "_workspace_from_log", lambda _job, _log_path: workspace)
    monkeypatch.setattr(
        source,
        "_verify_persisted_receipts",
        lambda **_kwargs: {
            "body_revision": "body-r0001",
            "canonical_body_id": "canonical-body",
            "source_binding": str(tmp_path / "binding.json"),
            "source_binding_sha256": "b" * 64,
            "body_review": str(tmp_path / "review.json"),
            "body_review_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(source, "person_library", lambda: tmp_path / "people")
    monkeypatch.setattr(
        source,
        "load_profile",
        lambda *_args, **_kwargs: {
            "source": {
                "kind": "stash-performer",
                "performer_id": STASH_PERFORMER_ID,
                "performer_name": "Fixture",
            }
        },
    )
    return repo, job_path, job, policy_path, policy


def test_boolean_job_version_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, job_path, job, _policy_path, _policy = _fixture(tmp_path, monkeypatch)
    job["version"] = True
    _write_json(job_path, job)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="body job format/version mismatch"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_boolean_source_enqueue_version_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, job_path, job, _policy_path, _policy = _fixture(tmp_path, monkeypatch)
    job["source_enqueue_authority"]["version"] = True
    _write_json(job_path, job)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="source enqueue authority format/version mismatch"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_boolean_retention_version_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, job_path, job, _policy_path, _policy = _fixture(tmp_path, monkeypatch)
    job["ab_baseline_retention"]["version"] = True
    _write_json(job_path, job)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="A/B retention authority is malformed"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_boolean_source_policy_version_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, _job_path, _job, policy_path, policy = _fixture(tmp_path, monkeypatch)
    policy["version"] = True
    _write_json(policy_path, policy)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="retained-source policy format/version mismatch"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_numeric_float_versions_remain_v1_compatible(tmp_path: Path, monkeypatch) -> None:
    repo, job_path, job, policy_path, policy = _fixture(tmp_path, monkeypatch)
    job["version"] = 1.0
    job["source_enqueue_authority"]["version"] = 1.0
    job["ab_baseline_retention"]["version"] = 1.0
    policy["version"] = 1.0
    _write_json(job_path, job)
    _write_json(policy_path, policy)

    result = source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo, expected_revision=REVISION)

    assert result["source_mode"] == "revision-bound-succeeded-body-build"
    assert result["stash_performer_id"] == STASH_PERFORMER_ID
    assert result["safe_source_lineage_passed"] is True
    assert result["comparison_only"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["production_activation"] is False
