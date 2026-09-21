param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [Parameter(Mandatory = $true)][string]$MotionDriverSourceRef,
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
    throw "P2 ExAvatar animation execution-input planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P2 ExAvatar animation execution-input planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P2Root)) {
    $P2Root = Join-Path $TeacherWorkRoot "p2-animated-teacher"
}
$P2Root = Need-Directory -Path $P2Root -Label "P2 work root"

$animationPlan = Need-File -Path (Join-Path $P2Root "p2-animation-plan.json") -Label "P2 animation plan"
$identityRoot = Need-Directory -Path (Join-Path $P2Root "animation-input\exavatar-identity") -Label "P2 ExAvatar animation identity root"
$identityReceipt = Need-File -Path (Join-Path $identityRoot "p2-exavatar-animation-identity.json") -Label "P2 ExAvatar animation identity receipt"

$motionWorkspace = Need-Directory -Path (Join-Path $P2Root "motion-preparation") -Label "P2 motion preparation workspace"
$motionReceipt = Need-File -Path (Join-Path $motionWorkspace "motion-preparation-receipt.json") -Label "P2 motion preparation receipt"
$motionOutputRoot = Need-Directory -Path (Join-Path $motionWorkspace "output") -Label "P2 motion preparation output root"

$outputRoot = Join-Path $P2Root "animation-input\exavatar-execution"
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$outputPath = Join-Path $outputRoot "p2-exavatar-animation-execution-input.json"
if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P2 ExAvatar animation execution input already exists: $outputPath"
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - EXAVATAR ANIMATION EXECUTION INPUT"
Write-Host "P2 animation plan:     $animationPlan"
Write-Host "Identity receipt:      $identityReceipt"
Write-Host "Motion receipt:        $motionReceipt"
Write-Host "TRAIN motion driver:   $MotionDriverSourceRef"
Write-Host "Output:                 $outputPath"
Write-Host "Held-out disclosure:   FALSE"
Write-Host "Animation started:     FALSE"
Write-Host "P2 acceptance:         FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"
Write-Host ""

$argsList = @(
    "-m", "bodyrig.photoreal_p2_exavatar_animation_execution_input",
    "--animation-plan", $animationPlan,
    "--identity-receipt", $identityReceipt,
    "--identity-root", $identityRoot,
    "--motion-receipt", $motionReceipt,
    "--motion-output-root", $motionOutputRoot,
    "--motion-driver-source-ref", $MotionDriverSourceRef,
    "--out", $outputPath
)
if ($ReuseExisting) {
    $argsList += "--reuse-existing"
}

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P2 ExAvatar animation execution-input planning failed with code $code."
}

$receipt = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P2 ExAvatar animation execution input") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "identity_artifact_bytes_reverified",
    "motion_driver_artifact_bytes_reverified",
    "train_motion_driver_only",
    "p2_animation_execution_authorized"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P2 ExAvatar animation execution-input authority missing: $field"
    }
}
foreach ($field in @(
    "held_out_evaluation_disclosed_to_animation",
    "animation_started",
    "p2_animated_teacher_acceptance_authority",
    "quest_distillation_authorized",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P2 ExAvatar animation execution-input crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P2 ExAvatar execution input: READY"
Write-Host "TRAIN motion driver:          $($receipt.motion_driver.source_ref)"
Write-Host "Motion frames:                $($receipt.motion_driver.frame_count)"
Write-Host "Identity bytes:               REVERIFIED"
Write-Host "Motion bytes:                 REVERIFIED"
Write-Host "Held-out disclosed:           FALSE"
Write-Host "Animation execution:          AUTHORIZED"
Write-Host "Animation started:            FALSE"
Write-Host "Animated acceptance:          FALSE"
Write-Host "Production:                   FALSE"
Write-Host "Plan: $outputPath"
exit 0
