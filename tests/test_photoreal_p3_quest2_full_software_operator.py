from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p3-quest2-full-software.ps1"


def test_full_software_operator_requires_clean_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source


def test_full_software_operator_regenerates_candidate_before_continuation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    candidate = "run-photoreal-v2-p3-quest2-refined-candidate.ps1"
    continuation = "run-photoreal-v2-p3-quest2-modular-continuation.ps1"
    assert candidate in source
    assert continuation in source
    assert source.index(candidate) < source.index(continuation)
    assert '"candidate"' in source
    assert '"continuation"' in source


def test_full_software_operator_isolates_child_exit_statements() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Resolve-PowerShellHost" in source
    assert "Run-ChildStage" in source
    assert "& $PowerShellHost -NoProfile -File $Script @Arguments" in source


def test_full_software_operator_stops_before_physical_pass_fail() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1" not in source
    assert "Physical PASS/FAIL:    NOT RUN" in source
    assert "Physical PASS/FAIL:     NOT RUN" in source
    assert 'physical_device_evidence_present = $false' in source
    assert 'physical_runtime_review_complete = $false' in source
    assert 'runtime_acceptance_authority = $false' in source
    assert 'photoreal_acceptance_authority = $false' in source
    assert 'production_activation = $false' in source


def test_full_software_summary_binds_candidate_and_final_review_chain() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "p3_device_distillation_plan_sha256",
        "candidate_manifest_sha256",
        "candidate_receipt_sha256",
        "continuation_summary_sha256",
        "final_execution_receipt_sha256",
        "runtime_review_plan_sha256",
        "physical_evidence_template_sha256",
    ):
        assert field in source


def test_full_software_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
