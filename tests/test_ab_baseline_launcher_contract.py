from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "start-ab-baseline.ps1").read_text(encoding="utf-8")


def test_launcher_is_checkout_bound_and_forces_retention() -> None:
    assert "bodyrig.ab_baseline_candidates" in SCRIPT
    assert "bodyrig\\ab_baseline_candidates.py" in SCRIPT
    assert "-RetainPrivateWorkspaceForAb" in SCRIPT
    assert "start-revision-bound-body-build.ps1" in SCRIPT
    assert "Pass exactly one of -PersonId or -PerformerId" in SCRIPT


def test_launcher_rechecks_frozen_candidate_revisions_after_enqueue() -> None:
    assert "-ExpectedMainRevision $mainRevision" in SCRIPT
    assert "-ExpectedPbrRevision $pbrRevision" in SCRIPT
    assert "-ExpectedThroughputRevision $throughputRevision" in SCRIPT
    assert "/api/v1/jobs/$JobId/cancel" in SCRIPT
    assert "Job $jobId is NOT dual-candidate baseline authority" in SCRIPT


def test_launcher_plan_is_create_only_and_non_activating() -> None:
    assert 'format = "bodyrig-dual-candidate-ab-baseline-plan"' in SCRIPT
    assert "Write-CreateOnlyJson" in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_required = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT


def test_launcher_keeps_throughput_candidate_build_separate() -> None:
    assert 'separate_candidate_body_build_required = $true' in SCRIPT
    assert "Throughput A/B still requires a separate succeeded body-build" in SCRIPT
    assert "run-pbr-ab-from-body-job.ps1 -BaselineJobId '$jobId'" in SCRIPT
