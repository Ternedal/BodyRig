from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p3-quest2-modular-continuation.ps1"


def test_modular_continuation_requires_clean_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source


def test_modular_continuation_runs_expected_software_stages() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "bodyrig.photoreal_p3_quest2_eye_student_runner",
        "run-photoreal-v2-p3-quest2-teacher-hair.ps1",
        "run-photoreal-v2-p3-quest2-fidelity-delta.ps1",
        "run-photoreal-v2-p3-quest2-final-manifest.ps1",
        "prepare-photoreal-v2-p3-quest2-runtime-review.ps1",
        "prepare-photoreal-v2-p3-quest2-physical-evidence-template.ps1",
    ):
        assert marker in source


def test_modular_continuation_never_runs_physical_pass_fail() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "record-photoreal-v2-p3-quest2-physical-runtime-review.ps1" not in source
    assert 'physical_device_evidence_present = $false' in source
    assert 'physical_runtime_review_complete = $false' in source
    assert 'runtime_acceptance_authority = $false' in source
    assert 'photoreal_acceptance_authority = $false' in source
    assert 'production_activation = $false' in source


def test_modular_continuation_keeps_hair_envelope_outside_hair_output() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '$hairEnvelopeDir = Join-Path $WorkRoot "hair-envelope"' in source
    assert '$hairRoot = Join-Path $WorkRoot "hair"' in source
    assert "-HairEnvelope" in source
    assert "-OutputRoot" in source


def test_modular_continuation_isolates_child_powershell_exit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Resolve-PowerShellHost" in source
    for script_var in (
        "$hairScript",
        "$fidelityScript",
        "$finalScript",
        "$reviewScript",
        "$templateScript",
    ):
        assert f"& $powerShellHost -NoProfile -File {script_var}" in source


def test_modular_continuation_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)


def test_modular_continuation_rejects_stale_candidate_adapter() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "photoreal_p3_exavatar_quest2_student_candidate.py" in source
    assert "currentCandidateAdapterSha" in source
    assert "candidate was built with a stale adapter revision" in source
    assert "p3_device_distillation_request_sha256" in source
    assert "p3_quest2_student_candidate_sha256" in source
