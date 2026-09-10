from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "start-throughput-retry-after-resume-signature-fix.ps1").read_text(encoding="utf-8")


def test_retry_is_pinned_to_failed_and_fixed_exact_revisions() -> None:
    assert "candidate/recovery-throughput-v3-current-main-20260908" in SCRIPT
    assert "ec743446d98809d693d01e51830f435fc3c09535" in SCRIPT
    assert "fix/throughput-v3-resume-signature-20260910" in SCRIPT
    assert "5fa01deb08399fda64e83db1329d4d2e83ad1bc2" in SCRIPT
    assert "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'" in SCRIPT


def test_retry_allows_only_reviewed_fix_scope() -> None:
    for path in (
        "bodyrig/bridges/hmr2_resume_bridge.py",
        "tests/test_hmr2_cross_job_resume.py",
        "tests/test_hmr2_resume_signature_regression.py",
    ):
        assert path in SCRIPT
    assert "merge-base --is-ancestor" in SCRIPT
    assert "diff --name-only" in SCRIPT
    assert "Compare-Object -ReferenceObject" in SCRIPT


def test_retry_replays_existing_plan_pbr_and_failed_candidate_authority() -> None:
    assert '"$BaselineJobId.json"' in SCRIPT
    assert '"$BaselineJobId-throughput-$FailedCandidateJobId.json"' in SCRIPT
    assert '"$BaselineJobId-throughput-$FailedCandidateJobId-pbr-gate.json"' in SCRIPT
    assert "plan-bound-human-review-authority.json" in SCRIPT
    assert "human-review.json" in SCRIPT
    assert "pbr_human_review_authority_sha256" in SCRIPT
    assert "pbr_human_review_sha256" in SCRIPT
    assert "human_visual_review_confirmed" in SCRIPT
    assert "-PromotionOptional" in SCRIPT
    assert "[string]$failedJob.status -ne 'failed'" in SCRIPT
    assert "[string]$failedSource.stash_performer_id -ne $performerId" in SCRIPT
    assert "$failedLog -notlike" in SCRIPT


def test_retry_switches_only_after_preflight_and_starts_exact_source_bound_job() -> None:
    preflight = SCRIPT.index("BodyRig throughput retry migration: preflight VERIFIED")
    update = SCRIPT.index("$null = & $updateScript -Branch $FixedThroughputRef -NoBrowser -SkipPlan")
    start = SCRIPT.index("& $startScript -PersonId $personId -ExpectedPerformerId $performerId -BaseUri $BaseUri")
    assert preflight < update < start
    assert "Assert-Checkout -Root $RepoRoot -ExpectedBranch $FixedThroughputRef -ExpectedRevision $FixedThroughputRevision" in SCRIPT
    assert "Assert-ServiceRevision -ExpectedRevision $FixedThroughputRevision" in SCRIPT
    assert "originFixedAfter" in SCRIPT
    assert "Try-CancelJob -JobId $newJobId" in SCRIPT


def test_retry_publishes_create_only_comparison_authority_and_blocks_ordinary_continuation() -> None:
    assert "Refusing to overwrite throughput retry authority" in SCRIPT
    assert 'format = \'bodyrig-throughput-retry-after-resume-signature-fix\'' in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_recorded = $true' in SCRIPT
    assert 'human_visual_authority_required = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT
    assert "Do not run the ordinary plan-bound throughput continuation" in SCRIPT
