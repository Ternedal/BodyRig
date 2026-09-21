param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$P0Root,
    [string]$P2Root = "",
    [string[]]$Window = @(),
    [Parameter(Mandatory = $true)][string]$ReviewedBy,
    [Parameter(Mandatory = $true)][string]$ReviewNotes,
    [switch]$ApproveHumanSelection,
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
    throw "P2 motion window selection requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion window selection requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$P0Root = Need-Directory -Path $P0Root -Label "P0 root"
foreach ($name in @(
    "scan-plan.json",
    "dataset-plan.json",
    "source-receipt.json",
    "frame-authorized-observations.json",
    "frame-index.json"
)) {
    Need-File -Path (Join-Path $P0Root $name) -Label "P0 $name" | Out-Null
}
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$handoffRoot = Need-Directory -Path (Join-Path $P2Root "motion-evidence") -Label "P2 motion evidence root"
$handoff = Need-File -Path (Join-Path $handoffRoot "p2-motion-evidence-handoff.json") -Label "P2 motion evidence handoff"
$privateIndex = Need-File -Path (Join-Path $handoffRoot "private-motion-source-index.json") -Label "Private P2 motion source index"
$sourceSelection = Need-File -Path (Join-Path $P2Root "p2-motion-source-selection.json") -Label "P2 motion source selection"
$motionInputRoot = Need-Directory -Path (Join-Path $P2Root "motion-input") -Label "P2 motion input root"
$inputPlan = Need-File -Path (Join-Path $motionInputRoot "p2-motion-input-plan.json") -Label "P2 motion input plan"
$normalization = Need-File -Path (Join-Path $motionInputRoot "p2-motion-normalization-selection.json") -Label "P2 motion normalization selection"
$outputPath = Join-Path $motionInputRoot "p2-motion-window-selection.json"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$baseArgs = @(
    "-m", "bodyrig.photoreal_p2_motion_window_selection_cli",
    "--handoff", $handoff,
    "--private-index", $privateIndex,
    "--source-selection", $sourceSelection,
    "--input-plan", $inputPlan,
    "--normalization-selection", $normalization,
    "--p0-root", $P0Root
)

$describeOutput = @(& $Python @baseArgs "--describe-only" 2>&1)
$describeCode = $LASTEXITCODE
if ($describeCode -ne 2) {
    foreach ($line in $describeOutput) { Write-Host ([string]$line) }
    throw "P2 motion window candidate discovery failed with code $describeCode."
}
if ($describeOutput.Count -lt 1) { throw "P2 motion window candidate discovery returned no output." }
try {
    $description = ([string]$describeOutput[-1]) | ConvertFrom-Json -Depth 100
}
catch {
    foreach ($line in $describeOutput) { Write-Host ([string]$line) }
    throw "P2 motion window candidate discovery did not return canonical JSON."
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION WINDOW SELECTION"
Write-Host "P0 root:             $P0Root"
Write-Host "P2 input plan:       $inputPlan"
Write-Host "Normalization:       $normalization"
Write-Host "Maximum clip length: $($description.maximum_total_window_seconds)s"
Write-Host "Output receipt:      $outputPath"
Write-Host "Source media rehash: NO"
Write-Host "Physical media work: NONE"
Write-Host "Production:          FALSE"
Write-Host "============================================================"
Write-Host ""

foreach ($source in @($description.sources)) {
    Write-Host ("{0} role={1} eye={2} duration={3}s candidates={4}" -f $source.source_ref, $source.role, $source.selected_eye, $source.source_duration_seconds, $source.candidate_count)
    foreach ($candidate in @($source.candidates)) {
        Write-Host ("  {0} t={1}s view={2} coverage={3}" -f $candidate.observation_ref, $candidate.timestamp_seconds, $candidate.view_bin, (@($candidate.coverage) -join ","))
    }
}
Write-Host ""

if (-not $ApproveHumanSelection) {
    Write-Host "HUMAN REVIEW REQUIRED."
    Write-Host "Choose exactly one observation per source and rerun with -Window."
    Write-Host "Syntax: 'src-...=obs-...,2.0,2.0' (before,after)."
    Write-Host "No video was decoded, deprojected, fitted, or rehashed."
    exit 2
}
if ($Window.Count -ne @($description.sources).Count) {
    throw "-Window must cover every selected source exactly once."
}

$recordArgs = @($baseArgs)
$recordArgs += @(
    "--reviewed-by", $ReviewedBy,
    "--review-notes", $ReviewNotes,
    "--approve-human-selection",
    "--out", $outputPath
)
foreach ($item in $Window) {
    $recordArgs += @("--window", $item)
}
if ($ReuseExisting) { $recordArgs += "--reuse-existing" }

$output = @(& $Python @recordArgs 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 motion window selection failed with code $code."
}

$receiptPath = Need-File -Path $outputPath -Label "P2 motion window selection"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "human_motion_window_selection_required",
    "human_motion_window_selection_complete",
    "motion_input_preparation_execution_authorized"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 motion window selection authority missing: $field"
    }
}
foreach ($field in @(
    "source_media_rehash_performed",
    "p2_animation_execution_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 motion window selection crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 motion window selection: RECORDED"
Write-Host "Windows:             $($receipt.selection_count)"
Write-Host "Maximum clip length: $($receipt.maximum_total_window_seconds)s"
Write-Host "Source media rehash: NO"
Write-Host "Physical media work: NONE"
Write-Host "Animation execution: FALSE"
Write-Host "Production:          FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
