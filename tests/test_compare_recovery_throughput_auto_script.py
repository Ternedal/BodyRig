from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "compare-recovery-throughput-auto.ps1").read_text(encoding="utf-8")
DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_AB.md").read_text(encoding="utf-8")


def test_auto_discovery_only_considers_succeeded_body_jobs_for_requested_person() -> None:
    assert '$job.kind -ne "body-build" -or $job.status -ne "succeeded"' in SCRIPT
    assert '$job.person_id -ne $PersonId' in SCRIPT
    assert 'bodyrig-recovery-proof.json' in SCRIPT


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


def test_runbook_forbids_cherry_picking_older_candidate_after_newer_failure() -> None:
    assert "newest" in DOC.lower()
    assert "does not search backwards for an older candidate" in DOC
    assert "Do not manually substitute an older passing pair" in DOC
    assert "compare-recovery-throughput-auto.ps1" in DOC
