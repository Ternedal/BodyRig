param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$TargetProfile,
    [string]$P2Root = "",
    [string]$P3Root = "",
    [switch]$ReuseExisting,
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
    throw "P3 device distillation planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 device distillation planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$TargetProfile = Need-File -Path $TargetProfile -Label "P3 target profile"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

if ([string]::IsNullOrWhiteSpace($P3Root)) {
    $P3Root = Join-Path $TeacherWorkRoot "p3-device-distillation"
}
$P3Root = [IO.Path]::GetFullPath($P3Root)
New-Item -ItemType Directory -Path $P3Root -Force | Out-Null

$p2HumanReview = Need-File -Path (Join-Path $P2Root "animated-review\p2-heldout-animated-human-review.json") -Label "P2 animated human review PASS receipt"
$executionInput = Need-File -Path (Join-Path $P2Root "animation-input\exavatar-execution\p2-exavatar-animation-execution-input.json") -Label "P2 ExAvatar execution input"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "Accepted ExAvatar teacher output root"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "Accepted ExAvatar identity export root"
$outputPath = Join-Path $P3Root "p3-device-distillation-plan.json"

if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P3 device distillation plan already exists: $outputPath"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P3 DEVICE DISTILLATION PLAN"
Write-Host "P2 human review:       $p2HumanReview"
Write-Host "ExAvatar input:        $executionInput"
Write-Host "Target profile:        $TargetProfile"
Write-Host "Teacher model source:  snapshot_4.pth + four identity JSONs"
Write-Host "Review MP4 as model:   FALSE"
Write-Host "Teacher bytes:         REVERIFY NOW"
Write-Host "Student selected:      FALSE"
Write-Host "Distillation run:      NOT STARTED"
Write-Host "Runtime acceptance:    FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_device_distillation_plan",
    "--p2-human-review", $p2HumanReview,
    "--execution-input", $executionInput,
    "--target-profile", $TargetProfile,
    "--teacher-output-root", $teacherOutputRoot,
    "--identity-root", $identityRoot,
    "--out", $outputPath
)
if ($ReuseExisting) { $argsList += "--reuse-existing" }

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P3 device distillation planning failed with code $code."
}

$plan = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P3 device distillation plan") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "teacher_source_bytes_reverified",
    "review_media_is_quality_evidence_not_teacher_source",
    "teacher_remains_visual_authority",
    "student_may_not_claim_fidelity_above_teacher",
    "fidelity_delta_measurement_required",
    "human_runtime_visual_acceptance_required",
    "distillation_adapter_required",
    "p3_distillation_execution_authorized"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $true) {
        throw "P3 device distillation plan authority missing: $field"
    }
}
foreach ($field in @(
    "distillation_adapter_selected",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $false) {
        throw "P3 device distillation plan crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P3 device distillation plan: READY"
Write-Host "Target:                      $($plan.target_profile.target_model)"
Write-Host "Teacher source artifacts:    $($plan.teacher_source_artifact_count)"
Write-Host "Review MP4 as teacher:       FALSE"
Write-Host "Student representation:      NOT SELECTED"
Write-Host "Distillation execution:      AUTHORIZED / NOT STARTED"
Write-Host "Runtime acceptance:          FALSE"
Write-Host "Production:                  FALSE"
Write-Host "Plan: $outputPath"
exit 0
