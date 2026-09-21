param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P2Root = "",
    [string[]]$MotionDriverSourceRef = @(),
    [string[]]$HeldOutValidationSourceRef = @(),
    [string]$ReviewedBy = "",
    [string]$ReviewNotes = "",
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
    throw "P2 motion source selection requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion source selection requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"
$handoffRoot = Need-Directory -Path (Join-Path $P2Root "motion-evidence") -Label "P2 motion evidence root"
$handoff = Need-File -Path (Join-Path $handoffRoot "p2-motion-evidence-handoff.json") -Label "P2 motion evidence handoff"
$privateIndex = Need-File -Path (Join-Path $handoffRoot "private-motion-source-index.json") -Label "Private P2 motion source index"
$outputPath = Join-Path $P2Root "p2-motion-source-selection.json"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$value = Get-Content -LiteralPath $handoff -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION SOURCE SELECTION"
Write-Host "Public handoff:       $handoff"
Write-Host "Private path map:     $privateIndex"
Write-Host "Output receipt:       $outputPath"
Write-Host "Source media rehash:  NO"
Write-Host "Animation execution:  FALSE"
Write-Host "P2 acceptance:        FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"
Write-Host ""
Write-Host "TRAIN motion-driver candidates:"
foreach ($candidate in @($value.motion_driver_candidates)) {
    Write-Host ("  {0}  group={1}  prep={2}" -f $candidate.source_ref, $candidate.group_ref, $candidate.preparation_mode)
}
Write-Host ""
Write-Host "HELD-OUT EVALUATION validation candidates:"
foreach ($candidate in @($value.held_out_motion_validation_candidates)) {
    Write-Host ("  {0}  group={1}  prep={2}" -f $candidate.source_ref, $candidate.group_ref, $candidate.preparation_mode)
}
Write-Host ""

if (-not $ApproveHumanSelection) {
    Write-Host "HUMAN REVIEW REQUIRED: select at least one TRAIN driver and one HELD-OUT EVALUATION validation source."
    Write-Host "No source was rehashed and no animation was started."
    Write-Host "Rerun with -MotionDriverSourceRef, -HeldOutValidationSourceRef, -ReviewedBy, -ReviewNotes and -ApproveHumanSelection."
    exit 2
}

if ($MotionDriverSourceRef.Count -lt 1) { throw "At least one -MotionDriverSourceRef is required." }
if ($HeldOutValidationSourceRef.Count -lt 1) { throw "At least one -HeldOutValidationSourceRef is required." }
if ([string]::IsNullOrWhiteSpace($ReviewedBy)) { throw "-ReviewedBy is required when approving human selection." }
if ([string]::IsNullOrWhiteSpace($ReviewNotes)) { throw "-ReviewNotes is required when approving human selection." }

$argsList = @(
    "-m", "bodyrig.photoreal_p2_motion_selection",
    "--handoff", $handoff,
    "--private-index", $privateIndex,
    "--reviewed-by", $ReviewedBy,
    "--review-notes", $ReviewNotes,
    "--approve-human-selection",
    "--out", $outputPath
)
foreach ($sourceRef in $MotionDriverSourceRef) {
    $argsList += @("--motion-driver-source-ref", $sourceRef)
}
foreach ($sourceRef in $HeldOutValidationSourceRef) {
    $argsList += @("--held-out-validation-source-ref", $sourceRef)
}
if ($ReuseExisting) {
    $argsList += "--reuse-existing"
}

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 motion source selection failed with code $code."
}

$receiptPath = Need-File -Path $outputPath -Label "P2 motion source selection receipt"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

foreach ($field in @(
    "source_media_rehash_required",
    "source_media_rehash_performed",
    "p2_animation_execution_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 motion source selection crossed authority boundary: $field"
    }
}
foreach ($field in @(
    "human_motion_source_selection_required",
    "human_motion_source_selection_complete",
    "motion_source_selection_authority",
    "p2_motion_input_authorized"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 motion source selection authority missing: $field"
    }
}

Write-Host ""
Write-Host "P2 motion source selection: RECORDED"
Write-Host "Motion-input preparation:   AUTHORIZED"
Write-Host "Animation execution:        FALSE"
Write-Host "Animated-teacher acceptance: FALSE"
Write-Host "Quest distillation:         FALSE"
Write-Host "Photoreal authority:        FALSE"
Write-Host "Production:                 FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
