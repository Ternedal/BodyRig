from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-exavatar-teacher.ps1"
TEACHER_CLI = ROOT / "bodyrig" / "photoreal_teacher_cli.py"


def test_static_teacher_operator_requires_explicit_identity_geometry_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '[ValidateSet("female", "male", "neutral")][string]$SmplxGender' in source
    assert '[ValidateSet("colmap", "virtual")][string]$CameraMode' in source
    assert '[Parameter(Mandatory = $true)][string]$AssetRoot' in source
    assert '[Parameter(Mandatory = $true)][string]$ReferenceModelRoot' in source
    assert "operator supplied" in source
    assert "Automatic restricted/model asset download remains DISABLED." in source


def test_static_teacher_operator_keeps_p3_and_acceptance_outside_scope() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "held-out" in source.lower()
    assert "Photoreal authority: FALSE" in source
    assert "Production:          FALSE" in source
    assert "Held-out likeness:  NOT YET ACCEPTED" in source
    assert "p3" not in source.lower()
    assert re.search(r"\bquest\b", source, flags=re.IGNORECASE) is None


def test_static_teacher_operator_is_resume_safe_before_training() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("--reuse-existing") >= 4
    assert "prepare-photoreal-exavatar-workspace.ps1" in source
    assert "prepare-photoreal-exavatar-runtime.ps1" in source
    assert "photoreal_exavatar_preprocess_cli" in source
    assert "photoreal_teacher_benchmark_plan_cli" in source
    assert "photoreal_exavatar_materializer_cli" in source
    assert "photoreal_exavatar_preflight_cli" in source
    assert "photoreal_exavatar_teacher_config_cli" in source


def test_static_teacher_operator_does_not_train_without_explicit_flag() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[switch]$RunTeacher" in source
    assert "if (-not $RunTeacher)" in source
    assert "LAUNCH READY" in source
    assert '"--reuse-existing"' in source
    assert "bodyrig.photoreal_teacher_cli" in source
    assert source.index("if (-not $RunTeacher)") < source.index("bodyrig.photoreal_teacher_cli")


def test_static_teacher_operator_reads_generic_runner_output_subdirectory() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '$teacherResultRoot = Need-Directory -Path (Join-Path $teacherOutput "output")' in source
    assert '(Join-Path $teacherResultRoot "teacher-manifest.json")' in source
    assert '(Join-Path $teacherResultRoot "review\\neutral-pose")' in source
    assert '(Join-Path $teacherOutput "teacher-manifest.json")' not in source


def test_static_teacher_operator_routes_interrupted_training_through_strict_resume() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    teacher_cli = TEACHER_CLI.read_text(encoding="utf-8")

    assert '"--workspace", $teacherOutput' in source
    assert '"--reuse-existing"' in source
    assert "resume_external_teacher_files_strict" in teacher_cli
    assert 'workspace / "output" / "teacher-manifest.json"' in teacher_cli
    assert "validate_external_teacher_files_strict" in teacher_cli


def test_static_teacher_operator_setup_is_opt_in() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[switch]$SetupPublicCode" in source
    assert "[switch]$SetupRuntime" in source
    assert "if (-not $SetupPublicCode)" in source
    assert "if (-not $SetupRuntime)" in source
    assert "setup-photoreal-exavatar-public-code.ps1" in source
    assert "setup-photoreal-exavatar-wsl.ps1" in source


def test_static_teacher_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)


def test_static_teacher_operator_provisions_only_default_workspace_parent() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "$usingDefaultLinuxWorkspaceRoot = [string]::IsNullOrWhiteSpace($LinuxWorkspaceRoot)" in source
    assert "Ensure-DefaultWslWorkspaceParent -WorkspaceRoot $LinuxWorkspaceRoot" in source
    assert 'if ($usingDefaultLinuxWorkspaceRoot)' in source
    assert '"/usr/bin/id", "-u"' not in source
    assert "/usr/bin/id -u" in source
    assert "-u root -- /bin/mkdir -p -- $parent" in source
    assert "-u root -- /bin/chown $owner -- $parent" in source
    assert "-u root -- /bin/chmod 0755 -- $parent" in source
    assert "-- /usr/bin/test -w $parent" in source
