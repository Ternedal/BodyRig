param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$HeldOutSourceRef,
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

if ($HeldOutSourceRef -notmatch '^[A-Za-z0-9._-]+$') {
    throw "HeldOutSourceRef contains characters that are unsafe for the canonical workspace path."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "P2 ExAvatar held-out evaluation requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 ExAvatar held-out evaluation requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
$teacherConfig = Need-File -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-config.json") -Label "ExAvatar teacher config"
$teacherOutputRoot = Need-Directory -Path (Join-Path $TeacherWorkRoot "exavatar-teacher-output\output") -Label "Accepted ExAvatar teacher output root"

if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

$evaluationInputRoot = Need-Directory -Path (Join-Path (Join-Path $P2Root "animation-evaluation\heldout-input") $HeldOutSourceRef) -Label "P2 held-out evaluation input root"
$evaluationInput = Need-File -Path (Join-Path $evaluationInputRoot "p2-exavatar-heldout-evaluation-input.json") -Label "P2 ExAvatar held-out evaluation input"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "P2 ExAvatar identity root"
$motionOutputRoot = Need-Directory -Path (Join-Path $P2Root "motion-preparation\output") -Label "P2 motion preparation output root"
$adapter = Need-File -Path (Join-Path $repoRoot "tools\photoreal_p2_exavatar_heldout_evaluation_adapter.py") -Label "Pinned P2 ExAvatar held-out evaluation adapter"

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $workspaceRoot = Join-Path $P2Root "animation-evaluation\heldout-execution"
    $Workspace = Join-Path $workspaceRoot $HeldOutSourceRef
}
$Workspace = [IO.Path]::GetFullPath($Workspace)
if (Test-Path -LiteralPath $Workspace) {
    throw "P2 ExAvatar held-out evaluation workspace already exists: $Workspace"
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - HELD-OUT EXAVATAR EVALUATION"
Write-Host "Evaluation input:      $evaluationInput"
Write-Host "HELD-OUT source ref:   $HeldOutSourceRef"
Write-Host "Teacher config:        $teacherConfig"
Write-Host "Identity root:         $identityRoot"
Write-Host "Motion root:           $motionOutputRoot"
Write-Host "Teacher output:        $teacherOutputRoot"
Write-Host "Adapter:               $adapter"
Write-Host "Workspace:             $Workspace"
Write-Host "Evaluation mode:       INFERENCE ONLY / HELD-OUT"
Write-Host "Teacher training:      FALSE"
Write-Host "Checkpoint mutation:   FALSE"
Write-Host "Source-media rehash:   NO"
Write-Host "Human P2 acceptance:   REQUIRED AFTER THIS RUN"
Write-Host "Quest distillation:    FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"
Write-Host ""
Write-Host "NOTE: this stage WILL run the frozen accepted teacher on HELD-OUT EVALUATION motion."
Write-Host "HELD-OUT bytes are disclosed only for post-training inference/evaluation and cannot authorize training."
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_exavatar_heldout_evaluation_runner",
    "--evaluation-input", $evaluationInput,
    "--teacher-config", $teacherConfig,
    "--identity-root", $identityRoot,
    "--motion-output-root", $motionOutputRoot,
    "--teacher-output-root", $teacherOutputRoot,
    "--bodyrig-repo-root", $repoRoot,
    "--adapter-script", $adapter,
    "--workspace", $Workspace
)

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 ExAvatar held-out evaluation failed with code $code."
}

$receiptPath = Need-File -Path (Join-Path $Workspace "heldout-evaluation-execution-receipt.json") -Label "P2 ExAvatar held-out evaluation execution receipt"
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if ([string]$receipt.held_out_source_ref -ne $HeldOutSourceRef) {
    throw "P2 held-out evaluation receipt source ref differs from requested source."
}
if ([string]$receipt.held_out_disclosure_purpose -ne "post-training-inference-only-evaluation") {
    throw "P2 held-out evaluation receipt disclosure purpose mismatch."
}
foreach ($field in @(
    "artifact_bytes_verified_by_core",
    "evaluation_complete",
    "inference_only",
    "held_out_evaluation_disclosed",
    "human_animated_visual_acceptance_required"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 held-out evaluation authority missing: $field"
    }
}
foreach ($field in @(
    "teacher_training_performed",
    "checkpoint_mutation_performed",
    "source_media_rehash_performed",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 held-out evaluation crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "HELD-OUT ExAvatar evaluation: COMPLETE"
Write-Host "Evaluation source:            $($receipt.held_out_source_ref)"
Write-Host "Evaluation frames:            $($receipt.held_out_frame_count)"
Write-Host "Evaluation artifacts:         $($receipt.evaluation_artifacts.Count)"
Write-Host "Generated bytes:              CORE VERIFIED"
Write-Host "Execution mode:               INFERENCE ONLY / HELD-OUT"
Write-Host "Teacher training:             FALSE"
Write-Host "Checkpoint mutation:          FALSE"
Write-Host "Held-out disclosure:          EVALUATION ONLY"
Write-Host "Human animated review:        REQUIRED"
Write-Host "Animated acceptance:          FALSE"
Write-Host "Quest distillation:           FALSE"
Write-Host "Production:                   FALSE"
Write-Host "Receipt: $receiptPath"
exit 0
