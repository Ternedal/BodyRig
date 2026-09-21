param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$P0Root,
    [string]$P2Root = "",
    [string[]]$Choice = @(),
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
    throw "P2 motion normalization selection requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 motion normalization selection requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$P0Root = Need-Directory -Path $P0Root -Label "P0 root"
$scanPlan = Need-File -Path (Join-Path $P0Root "scan-plan.json") -Label "P0 scan plan"
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
$outputPath = Join-Path $motionInputRoot "p2-motion-normalization-selection.json"
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

$baseArgs = @(
    "-m", "bodyrig.photoreal_p2_motion_normalization_selection_cli",
    "--handoff", $handoff,
    "--private-index", $privateIndex,
    "--source-selection", $sourceSelection,
    "--input-plan", $inputPlan,
    "--scan-plan", $scanPlan
)

$describeOutput = @(& $Python @baseArgs "--describe-only" 2>&1)
$describeCode = $LASTEXITCODE
if ($describeCode -notin @(0,2)) {
    foreach ($line in $describeOutput) { Write-Host ([string]$line) }
    throw "P2 motion normalization choice discovery failed with code $describeCode."
}
if ($describeOutput.Count -lt 1) { throw "P2 motion normalization choice discovery returned no output." }
$describeLine = [string]$describeOutput[-1]
try {
    $description = $describeLine | ConvertFrom-Json -Depth 100
}
catch {
    foreach ($line in $describeOutput) { Write-Host ([string]$line) }
    throw "P2 motion normalization choice discovery did not return canonical JSON."
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P2 MOTION NORMALIZATION SELECTION"
Write-Host "P0 scan authority:    $scanPlan"
Write-Host "P2 input plan:        $inputPlan"
Write-Host "Output receipt:       $outputPath"
Write-Host "Source media rehash:  NO"
Write-Host "Animation execution:  FALSE"
Write-Host "Production:           FALSE"
Write-Host "============================================================"
Write-Host ""
foreach ($item in @($description.choices)) {
    $eyes = (@($item.allowed_eyes) -join ",")
    $viewports = if (@($item.allowed_viewport_ids).Count -gt 0) { @($item.allowed_viewport_ids) -join "," } else { "<none>" }
    Write-Host ("{0}  role={1} projection={2} stereo={3} strategy={4}" -f $item.source_ref, $item.role, $item.projection, $item.stereo_layout, $item.normalization_strategy)
    Write-Host ("  allowed eyes: {0}" -f $eyes)
    Write-Host ("  allowed viewports: {0}" -f $viewports)
    Write-Host ("  human selection required: {0}" -f ([bool]$item.human_selection_required))
}
Write-Host ""

$humanRequired = [bool]$description.human_normalization_selection_required
if ($humanRequired -and -not $ApproveHumanSelection) {
    Write-Host "HUMAN REVIEW REQUIRED."
    Write-Host "Rerun with -Choice values such as 'src-...=left@v00' and -ApproveHumanSelection."
    Write-Host "No video was decoded, deprojected, fitted, or rehashed."
    exit 2
}
if ($humanRequired -and $Choice.Count -lt 1) {
    throw "At least one -Choice is required when human normalization selection is required."
}

$recordArgs = @(
    $baseArgs,
    "--reviewed-by", $ReviewedBy,
    "--review-notes", $ReviewNotes,
    "--out", $outputPath
)
foreach ($item in $Choice) {
    $recordArgs += @("--choice", $item)
}
if ($ApproveHumanSelection) { $recordArgs += "--approve-human-selection" }
if ($ReuseExisting) { $recordArgs += "--reuse-existing" }

$output = @(& $Python @recordArgs 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 motion normalization selection failed with code $code."
}

$receiptPath = Need-File -Path $outputPath -Label "P2 motion normalization selection"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($receipt.human_normalization_selection_complete -isnot [bool] -or $receipt.human_normalization_selection_complete -ne $true) {
    throw "P2 motion normalization selection is not complete."
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
        throw "P2 motion normalization selection crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 motion normalization selection: RECORDED"
Write-Host "Selections:          $($receipt.selection_count)"
Write-Host "Source media rehash: NO"
Write-Host "Animation execution: FALSE"
Write-Host "Production:          FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
