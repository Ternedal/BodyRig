from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "prepare-recovery-throughput-review.ps1").read_text(encoding="utf-8")


def test_review_preparation_uses_canonical_auto_discovery_and_machine_gate() -> None:
    assert 'compare-recovery-throughput-auto.ps1' in SCRIPT
    assert '"Canonical recovery A/B machine audit did not pass' in SCRIPT
    assert '-PersonId $PersonId' in SCRIPT
    assert '-Out $scratchAudit' in SCRIPT
    assert '-RepoRoot $RepoRoot' in SCRIPT
    assert 'bodyrig-recovery-throughput-sampling-audit' in SCRIPT
    assert 'eligible-for-human-ab-review' in SCRIPT


def test_review_preparation_rejects_authority_boundary_drift_before_bundle() -> None:
    assert 'Get-JsonPropertyValue -Object $audit -Name "promotion_authority"' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $audit -Name "production_activation"' in SCRIPT
    assert '$promotion -ne $false -or $production -ne $false' in SCRIPT
    assert 'crossed the promotion/production authority boundary' in SCRIPT


def test_review_preparation_passes_exact_auto_selected_pair_to_canonical_bundle_builder() -> None:
    assert 'build-recovery-throughput-review-bundle.ps1' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $audit -Name "baseline_job_id"' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $audit -Name "candidate_job_id"' in SCRIPT
    assert '"-BaselineJobId", $baselineJobId' in SCRIPT
    assert '"-CandidateJobId", $candidateJobId' in SCRIPT
    assert 'Step 2/2: rebuild full machine gate and create immutable human-review bundle' in SCRIPT


def test_review_preparation_uses_ephemeral_machine_scratch_and_cleans_it() -> None:
    assert '[Guid]::NewGuid().ToString("N")' in SCRIPT
    assert 'GetTempPath()' in SCRIPT
    assert 'finally {' in SCRIPT
    assert 'Remove-Item -LiteralPath $scratchAudit' in SCRIPT


def test_review_preparation_opens_only_completed_bundle_and_supports_no_browser() -> None:
    assert '[switch]$NoBrowser' in SCRIPT
    assert 'review-bundle.json' in SCRIPT
    assert 'index.html' in SCRIPT
    assert 'if (-not $NoBrowser)' in SCRIPT
    assert 'Start-Process -FilePath $index' in SCRIPT
    assert 'Review bundle build reported success but canonical bundle files are missing.' in SCRIPT


def test_review_preparation_does_not_perform_human_review_restore_or_promotion() -> None:
    forbidden = (
        'update-windows.ps1',
        'record-recovery-throughput-human-review.ps1 -BundleDir',
        'merge_pull_request',
        'complete-reference-acceptance.ps1',
        'production_activation = true',
        'promotion_authority = true',
    )
    for text in forbidden:
        assert text not in SCRIPT
    assert 'No human PASS, promotion, production activation, checkout switch or restore was performed.' in SCRIPT
    assert 'record-recovery-throughput-human-review.ps1' in SCRIPT
    assert 'restore canonical Person Studio authority' in SCRIPT
