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


def test_static_teacher_run_requires_fresh_exavatar_readiness_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    head = source.index("git -C $repoRoot rev-parse HEAD")
    launch_guard = source.index("if (-not $RunTeacher)")
    readiness = source.index("FINAL READ-ONLY EXAVATAR READINESS GATE")
    trainer = source.index("bodyrig.photoreal_teacher_cli")

    assert head < launch_guard < readiness < trainer
    assert "check-photoreal-v2-exavatar-readiness.ps1" in source
    assert '"-AssetRoot", $AssetRoot' in source
    assert '"-ReferenceModelRoot", $ReferenceModelRoot' in source
    assert '"-SmplxGender", $SmplxGender' in source
    assert '"-CameraMode", $CameraMode' in source
    assert '"-Distribution", $Distribution' in source
    assert '"-LinuxDependencyRoot", $LinuxDependencyRoot' in source
    assert '"-LinuxRuntimePython", $LinuxRuntimePython' in source
    assert '"-LinuxMaterializerPython", $LinuxMaterializerPython' in source
    assert "$head -notmatch '^[0-9a-f]{40}$'" in source
    assert "$readiness.exavatar_launch_prerequisites_ready -ne $true" in source
    assert "[string]$readiness.bodyrig_revision -ne $head" in source
    assert '[string]$readiness.bodyrig_branch -ne "main"' in source
    assert "$readiness.bodyrig_checkout_clean -ne $true" in source


def test_static_teacher_run_persists_hash_bound_launch_and_completion_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    readiness = source.index("FINAL READ-ONLY EXAVATAR READINESS GATE")
    launch_receipt = source.index("bodyrig-photoreal-exavatar-teacher-launch-authority")
    trainer = source.index("bodyrig.photoreal_teacher_cli")
    manifest = source.index('Need-File -Path (Join-Path $teacherResultRoot "teacher-manifest.json")')
    completion = source.index("bodyrig-photoreal-exavatar-teacher-completion-evidence")

    assert readiness < launch_receipt < trainer < manifest < completion
    assert 'Join-Path $TeacherWorkRoot "exavatar-teacher-launch-evidence"' in source
    assert 'Copy-Item -LiteralPath $readinessReport -Destination $boundReadiness' in source
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $boundReadiness" in source
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $teacherConfig" in source
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $teacherInput" in source
    assert "launch_authority_sha256 = $launchAuthoritySha" in source
    assert "teacher_manifest_sha256 = $teacherManifestSha" in source
    assert "training_authorized = $true" in source
    assert "training_complete = $true" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source


def test_static_teacher_operator_blocks_training_until_smplx_fit_review() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    preprocess = source.index("=== 5/7 PREPROCESS AUTHORIZED TRAINING FRAMES ===")
    review_block = source.index("BLOCKED FOR HUMAN SMPL-X FIT REVIEW")
    runtime = source.index("=== 6/7 BUILD / REVALIDATE PINNED CUDA RUNTIME ===")
    trainer = source.index("bodyrig.photoreal_teacher_cli")

    assert "[switch]$AcceptSmplxFit" in source
    assert "-AcceptSmplxFit and -RunTeacher are intentionally mutually exclusive" in source
    assert "--accept-fit-review" in source
    assert "--validate-fit-review" in source
    assert preprocess < review_block < runtime < trainer


def test_rebuild_archives_stale_derived_exavatar_state_before_regeneration() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Move-RebuildArtifact" in source
    for name in (
        "exavatar-benchmark-plan.json",
        "exavatar-materialization",
        "exavatar-teacher-config.json",
        "exavatar-teacher-output",
        "exavatar-teacher-launch-evidence",
    ):
        assert f'"{name}"' in source
    assert "exavatar-rebuild-archive" in source
    assert "Canonical teacher-input.json and P0 authority were preserved." in source
    assert source.index("=== REBUILD: ARCHIVED STALE EXAVATAR DERIVED STATE ===") < source.index(
        "=== 1/7 STRICT EXAVATAR BENCHMARK PLAN ==="
    )
