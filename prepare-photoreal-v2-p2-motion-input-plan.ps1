param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = "",
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
    throw "P2 motion input planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion input planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

$handoffRoot = Need-Directory -Path (Join-Path $P2Root "motion-evidence") -Label "P2 motion evidence root"
$handoff = Need-File -Path (Join-Path $handoffRoot "p2-motion-evidence-handoff.json") -Label "P2 motion evidence handoff"
$privateIndex = Need-File -Path (Join-Path $handoffRoot "private-motion-source-index.json") -Label "Private P2 motion source index"
$selection = Need-File -Path (Join-Path $P2Root "p2-motion-source-selection.json") -Label "P2 motion source selection"

$inputRoot = Join-Path $P2Root "motion-input"
New-Item -ItemType Directory -Path $inputRoot -Force | Out-Null
$outputPath = Join-Path $inputRoot "p2-motion-input-plan.json"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION INPUT PLAN"
Write-Host "Selection:             $selection"
Write-Host "Private path map:      $privateIndex"
Write-Host "Output plan:           $outputPath"
Write-Host "Source media rehash:   NO"
Write-Host "Media preparation:     NOT RUN"
Write-Host "Animation execution:   FALSE"
Write-Host "P2 acceptance:         FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_motion_input_plan",
    "--handoff", $handoff,
    "--private-index", $privateIndex,
    "--selection", $selection,
    "--out", $outputPath
)
if ($ReuseExisting) {
    $argsList += "--reuse-existing"
}

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 motion input planning failed with code $code."
}

$planPath = Need-File -Path $outputPath -Label "P2 motion input plan"
$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

foreach ($field in @(
    "build_private",
    "motion_parameter_extraction_required",
    "motion_input_plan_ready",
    "p2_motion_input_authorized"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $true) {
        throw "P2 motion input plan authority missing: $field"
    }
}
foreach ($field in @(
    "source_media_rehash_required",
    "source_media_rehash_performed",
    "motion_input_preparation_execution_authorized",
    "p2_animation_execution_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($plan.$field -isnot [bool] -or $plan.$field -ne $false) {
        throw "P2 motion input plan crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 motion input plan: READY"
Write-Host "Driver tasks:         $($plan.motion_driver_task_count)"
Write-Host "Validation tasks:     $($plan.held_out_motion_validation_task_count)"
Write-Host "Direct flat/mono:     $($plan.direct_flat_mono_task_count)"
Write-Host "Exact deprojection:   $($plan.exact_deprojection_task_count)"
Write-Host "Motion fitting:       $($plan.motion_fitting_backend) / camera=$($plan.motion_fitting_camera_mode)"
Write-Host "Source media rehash:  NO"
Write-Host "Media preparation:    NOT RUN"
Write-Host "Animation execution:  FALSE"
Write-Host "Production:           FALSE"
Write-Host "Plan: $planPath"
exit 0
