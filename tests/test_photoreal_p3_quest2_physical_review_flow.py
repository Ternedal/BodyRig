from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p3-quest2-physical-review-flow.ps1"


def test_physical_review_flow_chains_existing_authority_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1" in source
    assert "complete-photoreal-v2-p3-quest2-physical-evidence-review.ps1" in source
    assert "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1" in source
    assert "Machine-safe evidence is ready." in source


def test_physical_review_flow_resumes_without_overwriting_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"-ReuseExisting"' in source
    assert "Assert-HumanEvidenceMatchesPrefill" in source
    assert "Existing human review evidence revalidated against the exact machine prefill" in source
    assert "already has a final receipt; refusing to rewrite completed evidence" in source
    assert "Human visual review:      REQUIRED" in source
    assert "Machine evidence:         PREFILL ONLY" in source
    assert "complete-photoreal-v2-p3-quest2-physical-evidence-review.ps1" in source
    assert "REVIEW COMPLETE" not in source


def test_machine_prefill_reuse_requires_exact_current_plan_and_probe() -> None:
    source = PREFILL_SCRIPT.read_text(encoding="utf-8")
    assert "[switch]$ReuseExisting" in source
    assert "Existing machine-safe physical review prefill revalidated against the exact current plan/probe" in source
    assert "differs from the exact current runtime review plan and machine probe" in source
    assert "if (-not $ReuseExisting)" in source


def test_physical_review_flow_never_grants_production_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Production activation:    FALSE" in source
    assert "production_activation -ne $false" in source
    assert "runtime_acceptance_authority =" not in source
    assert "photoreal_acceptance_authority =" not in source


def test_physical_review_flow_uses_child_pwsh_processes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "& $Pwsh -NoLogo -NoProfile -File $Script @Arguments" in source
    assert "$code = $LASTEXITCODE" in source
    assert "failed with exit code $code" in source


def test_physical_review_flow_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
