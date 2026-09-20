param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$AssetRoot,
    [Parameter(Mandatory = $true)][string]$ReferenceModelRoot,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$SmplxGender,
    [Parameter(Mandatory = $true)][ValidateSet("colmap", "virtual")][string]$CameraMode,
    [string]$LinuxWorkspaceRoot = "",
    [string]$LinuxDependencyRoot = "/opt/bodyrig-exavatar/deps",
    [string]$LinuxRuntimePython = "/opt/bodyrig-exavatar/bin/python",
    [string]$LinuxMaterializerPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$WslExe = "wsl.exe",
    [string]$BodyRigPython = "",
    [switch]$SetupPublicCode,
    [switch]$SetupRuntime,
    [switch]$RunTeacher
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-BodyRigPython {
    param([string]$Requested,[Parameter(Mandatory = $true)][string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "BodyRig Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Python not found. Pass -BodyRigPython explicitly." }
    return $command.Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [int[]]$AllowedExitCodes = @(0)
    )
    $output = @(& $FilePath @Arguments 2>&1)
    $code = $LASTEXITCODE
    foreach ($line in $output) { Write-Host ([string]$line) }
    if ($AllowedExitCodes -notcontains $code) {
        throw "$Label failed with code $code."
    }
    return [int]$code
}

function Test-WslFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    & $WslExe -d $Distribution -- /usr/bin/test -f $Path 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-WslExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)
    & $WslExe -d $Distribution -- /usr/bin/test -x $Path 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    $output = @(& $WslExe -d $Distribution -- /usr/bin/wslpath -a -u $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$output[0])) {
        throw "Could not translate Windows path into WSL: $WindowsPath"
    }
    return ([string]$output[0]).Trim()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchName = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchName.Count -ne 1 -or ([string]$branchName[0]).Trim() -ne "main") {
    throw "ExAvatar static-teacher operator requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "ExAvatar static-teacher operator requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher continuation workspace"
$AssetRoot = Need-Directory -Path $AssetRoot -Label "ExAvatar asset root"
$ReferenceModelRoot = Need-Directory -Path $ReferenceModelRoot -Label "Reference model root"
$teacherInput = Need-File -Path (Join-Path $TeacherWorkRoot "teacher-input.json") -Label "Strict teacher input"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$inspectCode = @'
import json
import sys
from pathlib import Path
repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
from bodyrig.photoreal_teacher_authority import validate_teacher_input_document
value = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
validated = validate_teacher_input_document(value)
print(json.dumps({
    "performer_id": validated["performer_id"],
    "teacher_input_sha256": validated["teacher_input_sha256"],
    "photoreal_acceptance_authority": validated["photoreal_acceptance_authority"],
    "production_activation": validated["production_activation"],
}, sort_keys=True, separators=(",", ":")))
'@
$inspectRaw = @(& $Python -c $inspectCode $repoRoot $teacherInput)
if ($LASTEXITCODE -ne 0 -or $inspectRaw.Count -ne 1) { throw "Strict teacher input validation failed." }
try { $teacher = ([string]$inspectRaw[0]) | ConvertFrom-Json }
catch { throw "Strict teacher input validation returned invalid JSON." }
if ($teacher.photoreal_acceptance_authority -ne $false -or $teacher.production_activation -ne $false) {
    throw "Teacher input crossed downstream authority."
}
$performerId = [string]$teacher.performer_id
$teacherSha = ([string]$teacher.teacher_input_sha256).ToLowerInvariant()
if ($teacherSha -notmatch '^[0-9a-f]{64}$') { throw "Teacher input SHA-256 is invalid." }

if ([string]::IsNullOrWhiteSpace($LinuxWorkspaceRoot)) {
    $safePerformer = ($performerId -replace '[^A-Za-z0-9._-]+', '-').Trim('-','_','.')
    if ([string]::IsNullOrWhiteSpace($safePerformer)) { throw "Performer id cannot form a safe ExAvatar workspace id." }
    $LinuxWorkspaceRoot = "/opt/bodyrig-exavatar/workspaces/bodyrig-$safePerformer-$($teacherSha.Substring(0,12))"
}
if (-not $LinuxWorkspaceRoot.StartsWith('/') -or $LinuxWorkspaceRoot -eq "/") {
    throw "LinuxWorkspaceRoot must be a non-root absolute Linux path."
}
if (-not $LinuxDependencyRoot.StartsWith('/') -or $LinuxDependencyRoot -eq "/") {
    throw "LinuxDependencyRoot must be a non-root absolute Linux path."
}
if (-not $LinuxRuntimePython.StartsWith('/') -or -not $LinuxRuntimePython.EndsWith('/bin/python')) {
    throw "LinuxRuntimePython must be an absolute venv path ending in /bin/python."
}
if (-not $LinuxMaterializerPython.StartsWith('/')) {
    throw "LinuxMaterializerPython must be an absolute Linux path."
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL EXAVATAR STATIC TEACHER"
Write-Host "Performer:           $performerId"
Write-Host "Teacher input SHA:   $teacherSha"
Write-Host "SMPL-X prior:        $SmplxGender (operator supplied)"
Write-Host "Camera mode:         $CameraMode (operator supplied)"
Write-Host "Linux workspace:     $LinuxWorkspaceRoot"
Write-Host "Held-out eval:       EXTERNAL / NOT DISCLOSED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

$publicReceipt = "$($LinuxDependencyRoot.TrimEnd('/'))/bodyrig-public-dependencies.json"
if (-not (Test-WslFile -Path $publicReceipt)) {
    if (-not $SetupPublicCode) {
        Write-Host ""
        Write-Host "BLOCKED: pinned ExAvatar public dependencies are not installed."
        Write-Host "Rerun with -SetupPublicCode to invoke setup-photoreal-exavatar-public-code.ps1."
        Write-Host "Restricted/model assets will still NOT be downloaded."
        exit 2
    }
    $setupPublic = Need-File -Path (Join-Path $repoRoot "setup-photoreal-exavatar-public-code.ps1") -Label "ExAvatar public-code setup"
    $publicParams = @{
        Distribution = $Distribution
        LinuxDependencyRoot = $LinuxDependencyRoot
        WslExe = $WslExe
    }
    & $setupPublic @publicParams
    if ($LASTEXITCODE -ne 0 -or -not (Test-WslFile -Path $publicReceipt)) {
        throw "Pinned ExAvatar public-code setup did not produce its receipt."
    }
}

$runtimeRoot = $LinuxRuntimePython.Substring(0, $LinuxRuntimePython.Length - "/bin/python".Length)
$runtimeReceipt = "$runtimeRoot/bodyrig-exavatar-runtime-setup.json"
if (-not (Test-WslFile -Path $runtimeReceipt) -or -not (Test-WslExecutable -Path $LinuxRuntimePython)) {
    if (-not $SetupRuntime) {
        Write-Host ""
        Write-Host "BLOCKED: pinned ExAvatar runtime is not installed."
        Write-Host "Rerun with -SetupRuntime to invoke setup-photoreal-exavatar-wsl.ps1."
        exit 2
    }
    $setupRuntime = Need-File -Path (Join-Path $repoRoot "setup-photoreal-exavatar-wsl.ps1") -Label "ExAvatar runtime setup"
    $runtimeParams = @{
        Distribution = $Distribution
        LinuxPython = $LinuxRuntimePython
        WslExe = $WslExe
    }
    & $setupRuntime @runtimeParams
    if ($LASTEXITCODE -ne 0 -or -not (Test-WslFile -Path $runtimeReceipt)) {
        throw "Pinned ExAvatar runtime setup did not produce its receipt."
    }
}
if (-not (Test-WslExecutable -Path $LinuxMaterializerPython)) {
    throw "Materializer Python is missing in WSL: $LinuxMaterializerPython"
}

$linuxRepo = Convert-ToWslPath -WindowsPath $repoRoot
$linuxAssets = Convert-ToWslPath -WindowsPath $AssetRoot
$linuxReference = Convert-ToWslPath -WindowsPath $ReferenceModelRoot

$benchmarkPlan = Join-Path $TeacherWorkRoot "exavatar-benchmark-plan.json"
Write-Host ""
Write-Host "=== 1/7 STRICT EXAVATAR BENCHMARK PLAN ==="
$planArgs = @(
    "-m", "bodyrig.photoreal_teacher_benchmark_plan_cli",
    "--teacher-input", $teacherInput,
    "--out", $benchmarkPlan,
    "--reuse-existing"
)
$planCode = Invoke-Checked -FilePath $Python -Arguments $planArgs -Label "ExAvatar benchmark plan" -AllowedExitCodes @(0,2)
if ($planCode -eq 2) {
    Write-Host "BLOCKED: no authorized flat/mono ExAvatar training candidate exists."
    exit 2
}

$strictPreflight = Join-Path $TeacherWorkRoot "exavatar-strict-preflight.json"
$linuxPreflight = Convert-ToWslPath -WindowsPath $strictPreflight
Write-Host ""
Write-Host "=== 2/7 STRICT EXAVATAR ENVIRONMENT PREFLIGHT ==="
$preflightArgs = @(
    "-d", $Distribution, "--",
    "/usr/bin/env",
    "PYTHONPATH=$linuxRepo",
    "PYTHONNOUSERSITE=1",
    $LinuxRuntimePython,
    "-m", "bodyrig.photoreal_exavatar_preflight_cli",
    "--dependency-root", $LinuxDependencyRoot,
    "--asset-root", $linuxAssets,
    "--reference-model-root", $linuxReference,
    "--smplx-gender", $SmplxGender,
    "--out", $linuxPreflight,
    "--reuse-existing"
)
if ($CameraMode -eq "virtual") { $preflightArgs += "--no-colmap" }
$preflightCode = Invoke-Checked -FilePath $WslExe -Arguments $preflightArgs -Label "ExAvatar strict preflight" -AllowedExitCodes @(0,2)
if ($preflightCode -eq 2) {
    Write-Host ""
    Write-Host "BLOCKED: ExAvatar strict preflight found missing/drifted dependencies or model assets."
    Write-Host "Receipt: $strictPreflight"
    Write-Host "Automatic restricted/model asset download remains DISABLED."
    exit 2
}

$materialization = Join-Path $TeacherWorkRoot "exavatar-materialization"
$materializerTool = Need-File -Path (Join-Path $repoRoot "tools\photoreal_exavatar_materialize.py") -Label "ExAvatar materializer tool"
Write-Host ""
Write-Host "=== 3/7 MATERIALIZE EXACT AUTHORIZED TRAINING FRAMES ==="
$materializeArgs = @(
    "-m", "bodyrig.photoreal_exavatar_materializer_cli",
    "--benchmark-plan", $benchmarkPlan,
    "--workspace", $materialization,
    "--tool-path", $materializerTool,
    "--distribution", $Distribution,
    "--linux-python", $LinuxMaterializerPython,
    "--wsl-exe", $WslExe,
    "--reuse-existing"
)
Invoke-Checked -FilePath $Python -Arguments $materializeArgs -Label "ExAvatar materialization" | Out-Null

Write-Host ""
Write-Host "=== 4/7 BUILD / REVALIDATE ISOLATED WSL WORKSPACE ==="
$workspaceOperator = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-exavatar-workspace.ps1") -Label "ExAvatar workspace operator"
$workspaceParams = @{
    MaterializationWorkspace = $materialization
    StrictPreflightPath = $strictPreflight
    AssetRoot = $AssetRoot
    ReferenceModelRoot = $ReferenceModelRoot
    SmplxGender = $SmplxGender
    LinuxWorkspaceRoot = $LinuxWorkspaceRoot
    LinuxDependencyRoot = $LinuxDependencyRoot
    Distribution = $Distribution
    LinuxPython = $LinuxMaterializerPython
    WslExe = $WslExe
}
& $workspaceOperator @workspaceParams
if ($LASTEXITCODE -ne 0) { throw "ExAvatar workspace preparation failed." }

Write-Host ""
Write-Host "=== 5/7 PREPROCESS AUTHORIZED TRAINING FRAMES ==="
$preprocessArgs = @(
    "-d", $Distribution, "--",
    "/usr/bin/env",
    "PYTHONPATH=$linuxRepo",
    "PYTHONNOUSERSITE=1",
    $LinuxRuntimePython,
    "-m", "bodyrig.photoreal_exavatar_preprocess_cli",
    "--workspace-root", $LinuxWorkspaceRoot,
    "--camera-mode", $CameraMode,
    "--python", $LinuxRuntimePython,
    "--execute"
)
Invoke-Checked -FilePath $WslExe -Arguments $preprocessArgs -Label "ExAvatar preprocessing" | Out-Null

Write-Host ""
Write-Host "=== 6/7 BUILD / REVALIDATE PINNED CUDA RUNTIME ==="
$runtimeOperator = Need-File -Path (Join-Path $repoRoot "prepare-photoreal-exavatar-runtime.ps1") -Label "ExAvatar runtime operator"
$runtimePrepParams = @{
    LinuxWorkspaceRoot = $LinuxWorkspaceRoot
    Distribution = $Distribution
    LinuxPython = $LinuxRuntimePython
    WslExe = $WslExe
}
& $runtimeOperator @runtimePrepParams
$runtimeCode = $LASTEXITCODE
if ($runtimeCode -eq 2) {
    Write-Host "BLOCKED: ExAvatar runtime preflight is not ready."
    exit 2
}
if ($runtimeCode -ne 0) { throw "ExAvatar runtime preparation failed with code $runtimeCode." }

$teacherConfig = Join-Path $TeacherWorkRoot "exavatar-teacher-config.json"
$bridge = Need-File -Path (Join-Path $repoRoot "bodyrig\photoreal_exavatar_teacher_wsl_bridge.py") -Label "ExAvatar WSL bridge"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_exavatar_teacher_adapter.py") -Label "ExAvatar teacher adapter"
$linuxRuntimePreflight = "$($LinuxWorkspaceRoot.TrimEnd('/'))/runtime-preflight.json"
Write-Host ""
Write-Host "=== 7/7 HASH-BIND TEACHER CONFIG ==="
$configArgs = @(
    "-m", "bodyrig.photoreal_exavatar_teacher_config_cli",
    "--windows-python", $Python,
    "--bridge", $bridge,
    "--adapter", $adapter,
    "--linux-workspace-root", $LinuxWorkspaceRoot,
    "--linux-runtime-preflight", $linuxRuntimePreflight,
    "--linux-python", $LinuxRuntimePython,
    "--distribution", $Distribution,
    "--wsl-exe", $WslExe,
    "--out", $teacherConfig,
    "--reuse-existing"
)
Invoke-Checked -FilePath $Python -Arguments $configArgs -Label "ExAvatar teacher config" | Out-Null

$teacherOutput = Join-Path $TeacherWorkRoot "exavatar-teacher-output"
if (-not $RunTeacher) {
    Write-Host ""
    Write-Host "BODYRIG EXAVATAR STATIC TEACHER: LAUNCH READY"
    Write-Host "Teacher config:     $teacherConfig"
    Write-Host "Teacher input:      $teacherInput"
    Write-Host "Linux workspace:    $LinuxWorkspaceRoot"
    Write-Host "Next action:        rerun this exact operator with -RunTeacher"
    Write-Host "Human review:       REQUIRED AFTER TRAINING"
    Write-Host "Photoreal authority: FALSE"
    Write-Host "Production:          FALSE"
    exit 2
}

Write-Host ""
Write-Host "=== EXAVATAR STATIC TEACHER TRAIN + NEUTRAL REVIEW RENDERS ==="
$runArgs = @(
    "-m", "bodyrig.photoreal_teacher_cli",
    "--config", $teacherConfig,
    "--teacher-input", $teacherInput,
    "--workspace", $teacherOutput,
    "--reuse-existing"
)
Invoke-Checked -FilePath $Python -Arguments $runArgs -Label "ExAvatar static teacher run" | Out-Null

$teacherResultRoot = Need-Directory -Path (Join-Path $teacherOutput "output") -Label "Teacher result directory"
$manifest = Need-File -Path (Join-Path $teacherResultRoot "teacher-manifest.json") -Label "Teacher manifest"
$reviewRoot = Need-Directory -Path (Join-Path $teacherResultRoot "review\neutral-pose") -Label "Neutral-pose teacher review set"

Write-Host ""
Write-Host "BODYRIG EXAVATAR STATIC TEACHER: TRAINING COMPLETE / HUMAN REVIEW REQUIRED"
Write-Host "Teacher manifest:   $manifest"
Write-Host "Review renders:     $reviewRoot"
Write-Host "Expected renders:   50 neutral-pose images"
Write-Host "Held-out likeness:  NOT YET ACCEPTED"
Write-Host "Photoreal authority: FALSE"
Write-Host "Production:          FALSE"
exit 2
