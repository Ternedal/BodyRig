from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.pbr_ab_body_job_source as source


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
FLOOR = "9" * 40
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "run-pbr-ab-from-body-job-internal.ps1").read_text(encoding="utf-8")
CLONE_READY = (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict]:
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("BODYRIG_DATA_DIR", raising=False)

    repo = tmp_path / "repo"
    _write_json(
        repo / "contracts" / "pbr-ab-source-policy-v1.json",
        {
            "format": "bodyrig-pbr-ab-source-policy",
            "version": 1,
            "safe_source_floor_revision": FLOOR,
        },
    )

    job_root = local / "BodyRig" / "ui-jobs" / JOB_ID
    clone_output = job_root / "clone-output"
    acceptance = job_root / "acceptance"
    fidelity = job_root / "fidelity-review"
    for directory in (clone_output, acceptance, fidelity):
        directory.mkdir(parents=True, exist_ok=True)
    _write_json(clone_output / "bodyrig-sith-fitter-config.json", {"format": "fixture"})
    _write_json(acceptance / "bodyrig-acceptance.json", {"format": "fixture"})
    _write_json(fidelity / "review.json", {"format": "fixture"})

    workspace = local / "BodyRig" / "identity-workspaces" / f"{PERSON_ID}-fixture"
    sith_input = workspace / "sith-input-v1"
    _write_json(sith_input / "reconstruction.json", {"format": "reconstruction"})
    _write_json(sith_input / "reconstruction-authority.json", {"format": "authority"})

    log = job_root / "job.log"
    log.write_text(f"Private identity workspace: {workspace}\nBodyRig Stash clone: PASS\n", encoding="utf-8")
    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "succeeded",
        "bodyrig_revision": REVISION,
        "session_report": str(job_root / "physical-session.json"),
        "clone_output": str(clone_output),
        "acceptance_dir": str(acceptance),
        "fidelity_dir": str(fidelity),
        "log_path": str(log),
        "body_revision": "bodyrev-1",
        "canonical_body_id": "canonical-body",
        "source_binding_sha256": "c" * 64,
        "body_review_sha256": "d" * 64,
        "ab_baseline_retention": {
            "format": "bodyrig-ab-baseline-retention",
            "version": 1,
            "retain_private_workspace": True,
            "expected_bodyrig_revision": REVISION,
            "job_id": JOB_ID,
        },
    }
    _write_json(job_root / "job.json", job)
    return repo, job_root, job


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


def test_valid_succeeded_revision_bound_body_job_is_safe_retained_source(tmp_path: Path, monkeypatch) -> None:
    repo, _job_root, _job = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(source, "_git", _git_ok)

    result = source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo, expected_revision=REVISION)

    assert result["format"] == source.FORMAT
    assert result["source_mode"] == "revision-bound-succeeded-body-build"
    assert result["body_job_id"] == JOB_ID
    assert result["person_id"] == PERSON_ID
    assert result["bodyrig_revision"] == REVISION
    assert result["safe_source_floor_revision"] == FLOOR
    assert result["safe_source_lineage_passed"] is True
    assert len(result["job_json_sha256"]) == 64
    assert len(result["producer_log_sha256"]) == 64
    assert len(result["reconstruction_sha256"]) == 64
    assert result["comparison_only"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_standard_body_job_without_explicit_retention_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, job_root, job = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(source, "_git", _git_ok)
    job.pop("ab_baseline_retention")
    _write_json(job_root / "job.json", job)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="lacks revision-bound A/B"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_failed_body_job_is_rejected_even_when_workspace_exists(tmp_path: Path, monkeypatch) -> None:
    repo, job_root, job = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(source, "_git", _git_ok)
    job["status"] = "failed"
    _write_json(job_root / "job.json", job)

    with pytest.raises(source.PbrAbBodyJobSourceError, match="requires a succeeded body-build"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_body_job_must_match_exact_current_origin_main(tmp_path: Path, monkeypatch) -> None:
    repo, _job_root, _job = _setup(tmp_path, monkeypatch)

    def _git_stale(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return REVISION
        if args == ("rev-parse", "refs/remotes/origin/main"):
            return OTHER_REVISION
        raise AssertionError(args)

    monkeypatch.setattr(source, "_git", _git_stale)
    with pytest.raises(source.PbrAbBodyJobSourceError, match="requires exact current origin/main"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_pre_safe_source_lineage_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, _job_root, _job = _setup(tmp_path, monkeypatch)

    def _git_pre_safe(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD") or args == ("rev-parse", "refs/remotes/origin/main"):
            return REVISION
        if args[0:2] == ("cat-file", "-e"):
            return ""
        if args == ("merge-base", "--is-ancestor", FLOOR, REVISION):
            raise source.PbrAbBodyJobSourceError("not an ancestor")
        raise AssertionError(args)

    monkeypatch.setattr(source, "_git", _git_pre_safe)
    with pytest.raises(source.PbrAbBodyJobSourceError, match="not proven at/after safe-source floor"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_workspace_path_must_come_from_managed_bodyrig_root(tmp_path: Path, monkeypatch) -> None:
    repo, job_root, _job = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(source, "_git", _git_ok)
    outside = tmp_path / "outside" / f"{PERSON_ID}-fixture"
    (outside / "sith-input-v1").mkdir(parents=True)
    (job_root / "job.log").write_text(f"Private identity workspace: {outside}\n", encoding="utf-8")

    with pytest.raises(source.PbrAbBodyJobSourceError, match="outside BodyRig managed roots"):
        source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo)


def test_clone_ready_only_honors_exact_running_job_retention_marker() -> None:
    for token in (
        '"ab_baseline_retention"',
        '[string]$uiJob.status -ne "running"',
        '$jobRevision -ne $head',
        '[string]$uiJob.person_id -ne $BodyId',
        '$retention.retain_private_workspace -ne $true',
        '$retentionRevision -ne $head',
        '$KeepPrivateWorkspace = $true',
        'UI A/B baseline retention marker is not exactly bound',
    ):
        assert token in CLONE_READY


def test_body_job_wrapper_revalidates_before_and_after_strict_runner() -> None:
    assert "bodyrig.pbr_ab_body_job_source" in WRAPPER
    assert "$sourceBefore = Invoke-SourceProbe" in WRAPPER
    assert "$sourceAfter = Invoke-SourceProbe" in WRAPPER
    assert '"-BaselineCloneOutput", [string]$sourceBefore.baseline_clone_output' in WRAPPER
    assert '"-IdentityWorkspace", [string]$sourceBefore.identity_workspace' in WRAPPER
    assert '"run-pbr-ab-physical-review.ps1"' in WRAPPER
    assert '"body-job-source-authority.json"' in WRAPPER
    assert 'format = "bodyrig-pbr-ab-body-job-source-authority"' in WRAPPER
    assert "physical_acceptance_authority = $false" in WRAPPER
    assert "production_activation = $false" in WRAPPER
    assert "pbr_run_authority_sha256" in WRAPPER
