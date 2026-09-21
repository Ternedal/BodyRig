from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPT = ROOT / "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1"
TEMPLATE_SCRIPT = ROOT / "prepare-photoreal-v2-p3-quest2-physical-evidence-template.ps1"


def test_modular_physical_operator_requires_clean_checkout() -> None:
    source = RECORD_SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source


def test_modular_physical_operator_consumes_runtime_review_workspace() -> None:
    source = RECORD_SCRIPT.read_text(encoding="utf-8")
    assert "p3-device-runtime-review-plan.json" in source
    assert "p3-physical-runtime-review.json" in source
    assert "Runtime review plan:" in source


def test_modular_physical_operator_requires_real_evidence() -> None:
    source = RECORD_SCRIPT.read_text(encoding="utf-8")
    for field in (
        "operator_supplied",
        "physical_device_observed",
        "confirm_physical_device_review_complete",
    ):
        assert field in source


def test_modular_physical_operator_preserves_pass_fail_and_never_production() -> None:
    source = RECORD_SCRIPT.read_text(encoding="utf-8")
    assert '$status -eq "pass"' in source
    assert '$status -eq "fail"' in source
    assert "runtime_acceptance_authority" in source
    assert "photoreal_acceptance_authority" in source
    assert "Production activation:        FALSE" in source


def test_physical_template_is_deliberately_non_authoritative() -> None:
    source = TEMPLATE_SCRIPT.read_text(encoding="utf-8")
    assert 'decision = "REVIEW_REQUIRED"' in source
    assert "physical_device_observed = $false" in source
    assert "installed_student_hashes_verified_on_device = $false" in source
    assert "confirm_physical_device_review_complete = $false" in source
    assert "intentionally NOT valid review evidence yet" in source


def test_physical_template_binds_planned_artifact_hashes() -> None:
    source = TEMPLATE_SCRIPT.read_text(encoding="utf-8")
    assert "p3_device_runtime_review_plan_sha256" in source
    assert "student_artifacts" in source
    assert "relative_path = [string]$artifact.relative_path" in source
    assert "sha256 = [string]$artifact.sha256" in source


def test_modular_physical_scripts_parse_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    for script in (RECORD_SCRIPT, TEMPLATE_SCRIPT):
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{script.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
