from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "start-ab-baseline.ps1").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "preflight-ab-baseline.ps1").read_text(encoding="utf-8")


def test_launcher_is_checkout_bound_and_forces_retention() -> None:
    assert "bodyrig.ab_baseline_candidates" in SCRIPT
    assert "bodyrig\\ab_baseline_candidates.py" in SCRIPT
    assert "RetainPrivateWorkspaceForAb = $true" in SCRIPT
    assert "start-revision-bound-body-build.ps1" in SCRIPT
    assert "Pass exactly one of -PersonId or -PerformerId" in SCRIPT


def test_launcher_uses_named_splat_for_revision_bound_enqueue() -> None:
    assert "$startArgs = @{" in SCRIPT
    assert "RetainPrivateWorkspaceForAb = $true" in SCRIPT
    assert "BaseUri = $BaseUri" in SCRIPT
    assert "PersonId = $preflightPersonId" in SCRIPT
    assert "ExpectedPerformerId = $preflightPerformerId" in SCRIPT
    assert "$startedRaw = @(& $startScript @startArgs)" in SCRIPT
    assert '$startArgs = @(\n    "-RetainPrivateWorkspaceForAb"' not in SCRIPT


def test_launcher_runs_service_bound_physical_preflight_before_enqueue() -> None:
    assert "preflight-ab-baseline.ps1" in SCRIPT
    assert "service-bound read-only fail-fast preflight" in SCRIPT
    assert "No baseline job was enqueued" in SCRIPT
    assert SCRIPT.index("preflight-ab-baseline.ps1") < SCRIPT.index("start-revision-bound-body-build.ps1")
    assert "/api/v1/people/$resolvedPersonId/body/ab-baseline-preflight" in PREFLIGHT
    assert '[string]$_.source.performer_id -eq $PerformerId' in PREFLIGHT
    assert '[string]$source.performer_id' in PREFLIGHT
    assert ".source.id" not in PREFLIGHT
    assert "renderer_ready -ne $true" in PREFLIGHT
    assert "service_environment_bound -ne $true" in PREFLIGHT
    assert "readiness_output_persisted -ne $false" in PREFLIGHT


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
    assert "run-pbr-ab-from-body-job-plan-bound.ps1 -BaselineJobId '$jobId'" in SCRIPT
    assert "run-pbr-ab-from-body-job.ps1 -BaselineJobId '$jobId'" not in SCRIPT
