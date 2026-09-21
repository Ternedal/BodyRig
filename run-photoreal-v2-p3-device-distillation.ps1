param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$P2Root = "",
    [string]$P3Root = "",
    [string]$Workspace = "",
    [string]$BodyRigPython = ""
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P3 distillation execution requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 distillation execution requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$Config = Need-File -Path $Config -Label "P3 distillation adapter config"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

if ([string]::IsNullOrWhiteSpace($P3Root)) {
    $P3Root = Join-Path $TeacherWorkRoot "p3-device-distillation"
}
$P3Root = Need-Directory -Path $P3Root -Label "P3 work root"

$plan = Need-File -Path (Join-Path $P3Root "p3-device-distillation-plan.json") -Label "P3 device distillation plan"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "Accepted ExAvatar teacher output root"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "Accepted ExAvatar identity export root"

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Join-Path $P3Root "execution"
}
$Workspace = [IO.Path]::GetFullPath($Workspace)
if (Test-Path -LiteralPath $Workspace) {
    throw "P3 distillation workspace already exists: $Workspace"
}

$configJson = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ([string]$configJson.format -ne "bodyrig-photoreal-p3-device-distillation-config") {
    throw "P3 distillation config format mismatch."
}
if ($configJson.consumes_staged_teacher_only -isnot [bool] -or $configJson.consumes_staged_teacher_only -ne $true) {
    throw "P3 distillation adapter must consume staged teacher copies only."
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P3 DISTILLATION EXECUTION"
Write-Host "Plan:                     $plan"
Write-Host "Adapter config:           $Config"
Write-Host "Adapter:                  $($configJson.adapter)"
Write-Host "Representation:           $($configJson.student_representation)"
Write-Host "Teacher originals:        NOT PASSED IN ADAPTER PROTOCOL"
Write-Host "Teacher staging:          EXACT COPY + PRE/POST SHA VERIFY"
Write-Host "Workspace:                $Workspace"
Write-Host "Runtime visual acceptance: REQUIRED AFTER RUN"
Write-Host "Runtime acceptance:       FALSE"
Write-Host "Production:               FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_device_distillation_runner",
    "--config", $Config,
    "--plan", $plan,
    "--teacher-output-root", $teacherOutputRoot,
    "--identity-root", $identityRoot,
    "--workspace", $Workspace
)

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P3 distillation execution failed with code $code."
}

$receiptPath = Need-File -Path (Join-Path $Workspace "p3-device-distillation-execution-receipt.json") -Label "P3 distillation execution receipt"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

foreach ($field in @(
    "distillation_complete",
    "artifact_bytes_verified_by_core",
    "staged_teacher_only",
    "human_runtime_visual_acceptance_required"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P3 distillation receipt authority missing: $field"
    }
}
foreach ($field in @(
    "student_fidelity_claim_exceeds_teacher",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P3 distillation receipt crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P3 distillation execution: COMPLETE"
Write-Host "Student representation:    $($receipt.student_representation)"
Write-Host "Student artifacts:         $($receipt.student_artifacts.Count)"
Write-Host "Fidelity deltas:           $($receipt.fidelity_delta_measurements.Count)"
Write-Host "Teacher original paths:    NOT PASSED IN ADAPTER PROTOCOL"
Write-Host "Teacher staged bytes:      CORE VERIFIED PRE + POST"
Write-Host "Student bytes:             CORE VERIFIED"
Write-Host "Runtime visual review:     REQUIRED"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Production:                FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
