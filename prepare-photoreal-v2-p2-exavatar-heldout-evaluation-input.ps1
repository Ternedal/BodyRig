param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$HeldOutSourceRef,
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

if ($HeldOutSourceRef -notmatch '^[A-Za-z0-9._-]+$') {
    throw "HeldOutSourceRef contains characters that are unsafe for the canonical output path."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P2 ExAvatar held-out evaluation-input planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 ExAvatar held-out evaluation-input planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "Accepted ExAvatar teacher output root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

$executionInput = Need-File -Path (Join-Path $P2Root "animation-input\exavatar-execution\p2-exavatar-animation-execution-input.json") -Label "P2 TRAIN animation execution input"
$trainReceipt = Need-File -Path (Join-Path $P2Root "animation-execution\animation-execution-receipt.json") -Label "P2 TRAIN animation execution receipt"
$motionReceipt = Need-File -Path (Join-Path $P2Root "motion-preparation\motion-preparation-receipt.json") -Label "P2 motion preparation receipt"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "P2 ExAvatar identity root"
$motionOutputRoot = Need-Directory -Path (Join-Path $P2Root "motion-preparation\output") -Label "P2 motion preparation output root"

$heldOutInputRoot = Join-Path $P2Root "animation-evaluation\heldout-input"
$outputRoot = Join-Path $heldOutInputRoot $HeldOutSourceRef
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$outputPath = Join-Path $outputRoot "p2-exavatar-heldout-evaluation-input.json"
if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P2 ExAvatar held-out evaluation input already exists: $outputPath"
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - HELD-OUT EXAVATAR EVALUATION INPUT"
Write-Host "TRAIN execution:       $trainReceipt"
Write-Host "HELD-OUT source ref:   $HeldOutSourceRef"
Write-Host "Motion receipt:        $motionReceipt"
Write-Host "Output:                 $outputPath"
Write-Host "Training complete:      REQUIRED"
Write-Host "Teacher mode:           FROZEN / INFERENCE ONLY"
Write-Host "Held-out disclosure:    AUTHORIZED FOR EVALUATION ONLY"
Write-Host "Teacher training:       FALSE"
Write-Host "Checkpoint mutation:    FALSE"
Write-Host "Evaluation execution:   NOT STARTED"
Write-Host "Human P2 acceptance:    FALSE"
Write-Host "Production:             FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p2_exavatar_heldout_evaluation_input",
    "--execution-input", $executionInput,
    "--train-execution-receipt", $trainReceipt,
    "--motion-preparation-receipt", $motionReceipt,
    "--identity-root", $identityRoot,
    "--teacher-output-root", $teacherOutputRoot,
    "--motion-output-root", $motionOutputRoot,
    "--heldout-source-ref", $HeldOutSourceRef,
    "--out", $outputPath
)
if ($ReuseExisting) {
    $argsList += "--reuse-existing"
}

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 ExAvatar held-out evaluation-input planning failed with code $code."
}

$result = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P2 ExAvatar held-out evaluation input") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "frozen_teacher_checkpoint_bytes_reverified",
    "identity_artifact_bytes_reverified",
    "held_out_motion_artifact_bytes_reverified",
    "train_animation_complete",
    "train_animation_inference_only",
    "held_out_evaluation_disclosed_to_animation",
    "p2_heldout_animation_evaluation_authorized",
    "human_animated_visual_acceptance_required"
)) {
    if ($result.$field -isnot [bool] -or $result.$field -ne $true) {
        throw "P2 ExAvatar held-out evaluation authority missing: $field"
    }
}
foreach ($field in @(
    "teacher_training_authorized",
    "checkpoint_mutation_authorized",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($result.$field -isnot [bool] -or $result.$field -ne $false) {
        throw "P2 ExAvatar held-out evaluation crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "HELD-OUT evaluation input: READY"
Write-Host "Evaluation source:          $($result.held_out_motion.source_ref)"
Write-Host "Evaluation frames:          $($result.held_out_motion.frame_count)"
Write-Host "Frozen checkpoint:          REVERIFIED"
Write-Host "Held-out motion bytes:      REVERIFIED"
Write-Host "Teacher training:           FALSE"
Write-Host "Checkpoint mutation:        FALSE"
Write-Host "Evaluation execution:       AUTHORIZED / NOT STARTED"
Write-Host "Human animated acceptance:  FALSE"
Write-Host "Production:                 FALSE"
Write-Host "Plan: $outputPath"
exit 0
