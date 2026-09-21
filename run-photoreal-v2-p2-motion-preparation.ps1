param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$P0Root,
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$P2Root = "",
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
    throw "P2 motion preparation requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion preparation requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$P0Root = Need-Directory -Path $P0Root -Label "P0 root"
$Config = Need-File -Path $Config -Label "P2 motion preparation config"
$scanPlan = Need-File -Path (Join-Path $P0Root "scan-plan.json") -Label "P0 scan plan"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$handoffRoot = Need-Directory -Path (Join-Path $P2Root "motion-evidence") -Label "P2 motion evidence root"
$handoff = Need-File -Path (Join-Path $handoffRoot "p2-motion-evidence-handoff.json") -Label "P2 motion evidence handoff"
$privateIndex = Need-File -Path (Join-Path $handoffRoot "private-motion-source-index.json") -Label "Private P2 motion source index"
$selection = Need-File -Path (Join-Path $P2Root "p2-motion-source-selection.json") -Label "P2 motion source selection"
$motionInputRoot = Need-Directory -Path (Join-Path $P2Root "motion-input") -Label "P2 motion input root"
$inputPlan = Need-File -Path (Join-Path $motionInputRoot "p2-motion-input-plan.json") -Label "P2 motion input plan"
$normalizationSelection = Need-File -Path (Join-Path $motionInputRoot "p2-motion-normalization-selection.json") -Label "P2 motion normalization selection"
$windowSelection = Need-File -Path (Join-Path $motionInputRoot "p2-motion-window-selection.json") -Label "P2 motion window selection"

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Join-Path $P2Root "motion-preparation"
}
$Workspace = [IO.Path]::GetFullPath($Workspace)
if (Test-Path -LiteralPath $Workspace) {
    throw "P2 motion preparation workspace already exists: $Workspace"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION PREPARATION"
Write-Host "P0 scan authority:    $scanPlan"
Write-Host "P2 input plan:        $inputPlan"
Write-Host "Normalization:        $normalizationSelection"
Write-Host "Motion windows:       $windowSelection"
Write-Host "Adapter config:       $Config"
Write-Host "Workspace:            $Workspace"
Write-Host "Source media rehash:  NO"
Write-Host "Evaluation training:  FALSE"
Write-Host "Animation execution:  OPENS ONLY AFTER CORE-VERIFIED MOTION PATHS"
Write-Host "P2 acceptance:        FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"
Write-Host ""
Write-Host "NOTE: this is the first P2 stage that may decode/deproject selected videos and run motion fitting."
Write-Host "It does not rehash the full source media library."
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_motion_preparation_runner_cli",
    "--config", $Config,
    "--handoff", $handoff,
    "--private-index", $privateIndex,
    "--selection", $selection,
    "--input-plan", $inputPlan,
    "--normalization-selection", $normalizationSelection,
    "--window-selection", $windowSelection,
    "--scan-plan", $scanPlan,
    "--workspace", $Workspace
)

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 motion preparation failed with code $code."
}

$receiptPath = Need-File -Path (Join-Path $Workspace "motion-preparation-receipt.json") -Label "P2 motion preparation receipt"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

foreach ($field in @(
    "generated_artifact_bytes_verified_by_core",
    "motion_input_preparation_complete",
    "p2_animation_execution_authorized"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 motion preparation authority missing: $field"
    }
}
foreach ($field in @(
    "source_media_rehash_performed",
    "evaluation_appearance_training_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 motion preparation crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 motion preparation: COMPLETE"
Write-Host "Prepared source tasks: $($receipt.task_count)"
Write-Host "Generated bytes:       CORE VERIFIED"
Write-Host "Source media rehash:   NO"
Write-Host "P2 animation execution: AUTHORIZED"
Write-Host "Animated acceptance:   FALSE"
Write-Host "Quest distillation:    FALSE"
Write-Host "Production:            FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
