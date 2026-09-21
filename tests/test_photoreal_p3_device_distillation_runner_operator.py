from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p3-device-distillation.ps1"


def test_p3_runner_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_p3_runner_operator_never_passes_original_teacher_roots_to_adapter() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Teacher originals:        NOT PASSED IN ADAPTER PROTOCOL" in source
    assert "consumes_staged_teacher_only" in source
    assert "Teacher staging:          EXACT COPY + PRE/POST SHA VERIFY" in source


def test_p3_runner_operator_keeps_runtime_and_production_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "distillation_complete",
        "artifact_bytes_verified_by_core",
        "staged_teacher_only",
        "human_runtime_visual_acceptance_required",
        "student_fidelity_claim_exceeds_teacher",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_p3_runner_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
