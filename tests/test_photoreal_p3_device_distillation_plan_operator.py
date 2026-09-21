from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-device-distillation.ps1"


def test_p3_operator_requires_clean_main_and_exact_p2_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert "p2-heldout-animated-human-review.json" in source
    assert "p2-exavatar-animation-execution-input.json" in source


def test_p3_operator_uses_teacher_model_not_review_mp4() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "snapshot_4.pth + four identity JSONs" in source
    assert "Review MP4 as model:   FALSE" in source
    assert "review_media_is_quality_evidence_not_teacher_source" in source


def test_p3_operator_authorizes_distillation_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "teacher_source_bytes_reverified",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "fidelity_delta_measurement_required",
        "human_runtime_visual_acceptance_required",
        "distillation_adapter_required",
        "p3_distillation_execution_authorized",
        "distillation_adapter_selected",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_p3_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
