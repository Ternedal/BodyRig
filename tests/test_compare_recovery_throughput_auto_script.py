from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "compare-recovery-throughput-auto.ps1").read_text(encoding="utf-8")
DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_AB.md").read_text(encoding="utf-8")


def test_auto_discovery_only_considers_succeeded_body_jobs_for_requested_person() -> None:
    assert '$kind -ne "body-build" -or $status -ne "succeeded"' in SCRIPT
    assert '$personIdValue -ne $PersonId' in SCRIPT
    assert 'bodyrig-recovery-proof.json' in SCRIPT


def test_auto_discovery_reads_stale_json_shapes_without_strict_mode_property_access() -> None:
    assert "function Get-JsonPropertyValue" in SCRIPT
    assert '$Object.PSObject.Properties[$Name]' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $job -Name "format"' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $job -Name "kind"' in SCRIPT
    assert 'Get-JsonPropertyValue -Object $proof -Name "revision"' in SCRIPT
    assert "$job.format" not in SCRIPT
    assert "$proof.revision" not in SCRIPT


def test_auto_discovery_uses_candidate_sampling_revision_from_checked_out_code() -> None:
    assert "RECOVERY_TEMPORAL_SAMPLING_REVISION" in SCRIPT
    assert '$suffix = ";s:$samplingRevision"' in SCRIPT
    assert '$revision.EndsWith($suffix, [StringComparison]::Ordinal)' in SCRIPT


def test_auto_discovery_selects_latest_candidate_then_exact_parent_baseline() -> None:
    assert 'Where-Object { $_.IsCandidate } | Sort-Object Completed -Descending | Select-Object -First 1' in SCRIPT
    assert '$expectedBaselineRevision = $candidate.Revision.Substring(0, $candidate.Revision.Length - $suffix.Length)' in SCRIPT
    assert 'Where-Object { -not $_.IsCandidate -and $_.Revision -ceq $expectedBaselineRevision }' in SCRIPT
    assert 'Sort-Object Completed -Descending' in SCRIPT


def test_auto_discovery_delegates_evidence_validation_to_canonical_comparator() -> None:
    assert 'compare-recovery-throughput.ps1' in SCRIPT
    assert '"-BaselineJobId", $baseline.JobId' in SCRIPT
    assert '"-CandidateJobId", $candidate.JobId' in SCRIPT
    assert 'fail-closed auditor' in SCRIPT


def test_auto_discovery_has_no_job_or_evidence_mutation_commands() -> None:
    forbidden = (
        "Remove-Item",
        "Move-Item",
        "Copy-Item",
        "Set-Content",
        "Add-Content",
        "Out-File",
        "New-Item",
    )
    for command in forbidden:
        assert command not in SCRIPT


def test_runbook_routes_operator_to_auto_discovery_without_weakening_exact_pair_gate() -> None:
    assert "compare-recovery-throughput-auto.ps1" in DOC
    assert "newest-candidate + exact-parent-baseline" in (
        Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_REVIEW_PREP.md"
    ).read_text(encoding="utf-8")
    assert "For an exact recorded pair" in DOC
    assert "compare-recovery-throughput.ps1" in DOC
