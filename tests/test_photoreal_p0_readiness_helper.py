from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "review-tools" / "VERIFY_PHYSICAL_P0_READY.ps1"
CODEQL_WORKFLOW = ROOT / ".github" / "workflows" / "codeql.yml"


def test_readiness_helper_binds_operator_supplied_exact_revision() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[string]$ExpectedBodyRigRevision" in source
    assert "ExpectedBodyRigRevision must be one exact 40-character Git SHA" in source
    assert "summary.bodyrig_revision -ne $ExpectedBodyRigRevision" in source
    assert "status.bodyrig_revision -ne $ExpectedBodyRigRevision" in source
    assert "c98442a06eee32fb9ca0b8e386856bef58c8350c" not in source


def test_readiness_helper_discovers_exact_head_workflows_without_weakenable_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "head_sha=$Revision&per_page=100" in source
    assert '"ci"' in source
    assert '"windows-log-handle-regression"' in source
    assert '"loc-metrics"' in source
    assert '"codeql"' in source
    assert "[string[]]$RequiredWorkflowNames" not in source
    assert "has no completed successful run for the exact head" in source


def test_readiness_helper_binds_executing_verifier_to_tracked_git_blob_and_ci() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Get-VerifierProvenance" in source
    assert "rev-parse --show-toplevel" in source
    assert 'rev-parse "${revision}:$relativePath"' in source
    assert 'hash-object "--path=$relativePath" $scriptPath' in source
    assert "Executing readiness verifier differs from the tracked Git blob at verifier HEAD" in source
    assert "verifier_bodyrig_revision = $verifierRevision" in source
    assert "verifier_git_blob_oid = [string]$verifier.GitBlob" in source
    assert "verifier_script_sha256 = [string]$verifier.ScriptSha256" in source
    assert "verifier_verified_runs = $verifierWorkflowEvidence.Verified" in source

    verifier = source.index("$verifier = Get-VerifierProvenance")
    verifier_workflow = source.index("Get-ExactHeadWorkflowEvidence -Revision $verifierRevision", verifier)
    physical = source.index('"P0_PHYSICAL_VERIFICATION.json"')
    assert verifier < verifier_workflow < physical


def test_readiness_helper_keeps_physical_receipt_reusable_across_verifier_revisions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    physical_start = source.index("$physicalReceipt = [ordered]@{")
    physical_end = source.index('Write-Host "P0 physical verification: CREATED', physical_start)
    physical_creation = source[physical_start:physical_end]

    assert "exact_bodyrig_revision = $ExpectedBodyRigRevision" in physical_creation
    assert "verifier_bodyrig_revision" not in physical_creation
    assert "verifier_script_sha256" not in physical_creation


def test_codeql_qualification_is_available_on_stacked_pull_requests() -> None:
    source = CODEQL_WORKFLOW.read_text(encoding="utf-8")

    assert "name: codeql" in source
    assert "pull_request:\n  schedule:" in source
    assert "pull_request:\n    branches: [main]" not in source
    assert "push:\n    branches: [main]" in source


def test_readiness_helper_preserves_physical_proof_across_software_blockers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    physical = source.index('"P0_PHYSICAL_VERIFICATION.json"')
    workflow = source.index("Get-ExactHeadWorkflowEvidence -Revision $ExpectedBodyRigRevision", physical)
    blocked = source.index("exit 2", workflow)
    readiness = source.index('"P0_DOWNSTREAM_READINESS.json"', blocked)

    assert physical < workflow < blocked < readiness
    assert "P0 physical verification: REUSED" in source
    assert "Existing physical verification is not bound to the current evidence bytes" in source
    assert "downstream_teacher_flow_ready=false" in source
    assert "downstream_teacher_flow_ready=true" in source


def test_readiness_helper_is_windows_powershell_compatible_at_json_read_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    read_json = source[source.index("function Read-Json"):source.index("function Test-NumericExact")]
    assert "ConvertFrom-Json -Depth" not in read_json


def test_readiness_helper_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
