from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p3-quest2-refined-candidate.ps1"


def test_refined_candidate_operator_requires_clean_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires an exact clean BodyRig checkout" in source


def test_refined_candidate_operator_reuses_pinned_teacher_runtime() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "exavatar-teacher-config.json" in source
    assert 'Get-ConfigArg -Command $teacherCommand -Name "--distribution"' in source
    assert 'Get-ConfigArg -Command $teacherCommand -Name "--wsl-exe"' in source
    assert 'Get-ConfigArg -Command $teacherCommand -Name "--linux-python"' in source
    assert 'Get-ConfigArg -Command $teacherCommand -Name "--workspace-root"' in source
    assert "d45268730c779fae4118f1a361cf9ff639bc4d1e" in source


def test_refined_candidate_operator_runs_core_runner_inside_wsl() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "bodyrig.photoreal_p3_quest2_student_candidate_runner" in source
    assert '"PYTHONPATH=$repoWsl"' in source
    assert '"PYTHONNOUSERSITE=1"' in source
    assert '"--teacher-output-root", $teacherOutputWsl' in source
    assert '"--identity-root", $identityWsl' in source
    assert '"--workspace", $candidateWsl' in source


def test_refined_candidate_config_hash_binds_adapter_and_refined_runtime() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "photoreal_p3_exavatar_quest2_student_candidate.py" in source
    assert "revision = $adapterSha" in source
    assert "entrypoint = $adapterWsl" in source
    assert '"--exavatar-workspace-root"' in source
    assert '"--canonical-uv-template"' in source
    assert "Teacher authority:     REFINED ExAvatar geometry + RGB" in source


def test_refined_candidate_default_uv_is_pinned_sith_template() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "pathlib.Path.home().as_posix()" in source
    assert ".local/share/bodyrig/sith/data/smplx_uv.obj" in source
    assert "Canonical SMPL-X UV template is missing in WSL" in source


def test_refined_candidate_operator_never_grants_downstream_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "$manifest.p3_distillation_complete -ne $false" in source
    assert "$manifest.runtime_acceptance_authority -ne $false" in source
    assert "$manifest.photoreal_acceptance_authority -ne $false" in source
    assert "$manifest.production_activation -ne $false" in source
    assert "Physical review:        REQUIRED LATER" in source
    assert "Production:             FALSE" in source


def test_refined_candidate_operator_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)


def test_refined_candidate_operator_preflights_cuda_dependencies() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'required = ("numpy", "PIL", "pytorch3d", "nvdiffrast")' in source
    assert "torch.cuda.is_available()" in source
    assert "bodyrig.photoreal_p3_quest2_student_candidate_runner" in source
    assert "Pinned ExAvatar Quest2 candidate runtime preflight failed" in source
    assert "CUDA device:" in source
