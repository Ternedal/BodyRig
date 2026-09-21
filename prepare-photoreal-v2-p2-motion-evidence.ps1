param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = "",
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
    throw "P2 motion evidence handoff requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion evidence handoff requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherInput = Need-File -Path (Join-Path $TeacherWorkRoot "teacher-input.json") -Label "Strict teacher input"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$p2Plan = Need-File -Path (Join-Path $P2Root "p2-animation-plan.json") -Label "P2 animation plan"
$handoffRoot = Join-Path $P2Root "motion-evidence"
New-Item -ItemType Directory -Path $handoffRoot -Force | Out-Null
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION EVIDENCE HANDOFF"
Write-Host "Teacher input:      $teacherInput"
Write-Host "P2 plan:            $p2Plan"
Write-Host "Handoff root:       $handoffRoot"
Write-Host "Source media rehash: NO"
Write-Host "Human selection:     REQUIRED"
Write-Host "Animation execution: FALSE"
Write-Host "P2 acceptance:       FALSE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_motion_evidence",
    "--teacher-input", $teacherInput,
    "--p2-animation-plan", $p2Plan,
    "--out", $handoffRoot,
    "--reuse-existing"
)
$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -notin @(0,2)) {
    throw "P2 motion evidence handoff failed with code $code."
}

$handoff = Need-File -Path (Join-Path $handoffRoot "p2-motion-evidence-handoff.json") -Label "P2 motion evidence handoff"
$privateIndex = Need-File -Path (Join-Path $handoffRoot "private-motion-source-index.json") -Label "Private P2 motion source index"
$value = Get-Content -LiteralPath $handoff -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if ($value.source_media_rehash_performed -isnot [bool] -or $value.source_media_rehash_performed -ne $false) {
    throw "P2 motion handoff unexpectedly claims source rehash."
}
if ($value.human_motion_source_selection_required -isnot [bool] -or $value.human_motion_source_selection_required -ne $true) {
    throw "P2 motion handoff removed human source selection."
}
foreach ($field in @(
    "human_motion_source_selection_complete",
    "p2_motion_input_authorized",
    "p2_animation_execution_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($value.$field -isnot [bool] -or $value.$field -ne $false) {
        throw "P2 motion handoff crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 motion source handoff: READY FOR HUMAN SELECTION"
Write-Host "Public handoff: $handoff"
Write-Host "Private path map: $privateIndex"
Write-Host "Driver candidates (TRAIN): $($value.motion_driver_candidate_count)"
Write-Host "Validation candidates (HELD-OUT EVALUATION): $($value.held_out_motion_validation_candidate_count)"
Write-Host ""
Write-Host "No source file was rehashed and no animation was started."
Write-Host "Next boundary: explicit human selection of motion-driver and held-out validation source refs."
exit 2
