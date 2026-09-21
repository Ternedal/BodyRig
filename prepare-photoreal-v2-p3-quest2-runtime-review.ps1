param(
    [Parameter(Mandatory = $true)][string]$DistillationPlan,
    [Parameter(Mandatory = $true)][string]$FinalWorkspace,
    [string]$ReviewWorkspace = "",
    [switch]$ReuseExisting,
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-WindowsPython {
    param([string]$Requested,[string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "Windows Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Windows Python not found. Pass -WindowsPython explicitly."
    }
    return $command.Source
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 runtime review planning requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$DistillationPlan = Need-File -Path $DistillationPlan -Label "P3 distillation plan"
$FinalWorkspace = Need-Directory -Path $FinalWorkspace -Label "Final Quest2 P3 workspace"
$executionReceipt = Need-File -Path (Join-Path $FinalWorkspace "p3-device-distillation-execution-receipt.json") -Label "Final P3 execution receipt"
$studentOutput = Need-Directory -Path (Join-Path $FinalWorkspace "output") -Label "Final P3 student output"
$finalWorkspaceReceipt = Need-File -Path (Join-Path $FinalWorkspace "p3-quest2-final-workspace-receipt.json") -Label "Final Quest2 workspace receipt"

if ([string]::IsNullOrWhiteSpace($ReviewWorkspace)) {
    $ReviewWorkspace = Join-Path (Split-Path -Parent $FinalWorkspace) "p3-quest2-runtime-review"
} else {
    $ReviewWorkspace = [System.IO.Path]::GetFullPath($ReviewWorkspace)
}
if (Test-Path -LiteralPath $ReviewWorkspace) {
    if (-not $ReuseExisting) {
        throw "Quest2 runtime review workspace already exists: $ReviewWorkspace"
    }
} else {
    New-Item -ItemType Directory -Path $ReviewWorkspace | Out-Null
}
$ReviewWorkspace = Need-Directory -Path $ReviewWorkspace -Label "Quest2 runtime review workspace"
$outputPath = Join-Path $ReviewWorkspace "p3-device-runtime-review-plan.json"
if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "Quest2 runtime review plan already exists: $outputPath"
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 PHYSICAL RUNTIME REVIEW PLAN"
Write-Host "Revision:                 $head"
Write-Host "Distillation plan:        $DistillationPlan"
Write-Host "Final workspace:          $FinalWorkspace"
Write-Host "Final workspace receipt:  $finalWorkspaceReceipt"
Write-Host "Execution receipt:        $executionReceipt"
Write-Host "Student output:           $studentOutput"
Write-Host "Review workspace:         $ReviewWorkspace"
Write-Host "Student bytes:            REVERIFY NOW"
Write-Host "Physical Quest install:   REQUIRED"
Write-Host "Physical evidence:        NOT PRESENT"
Write-Host "Human visual review:      REQUIRED"
Write-Host "Runtime acceptance:       FALSE"
Write-Host "Photoreal acceptance:     FALSE"
Write-Host "Production:               FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_device_runtime_review_plan",
    "--plan", $DistillationPlan,
    "--execution-receipt", $executionReceipt,
    "--student-output-root", $studentOutput,
    "--out", $outputPath
)
if ($ReuseExisting) {
    $argsList += "--reuse-existing"
}
$output = @(& $python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Quest2 physical runtime review planning failed with code $code."
}

$result = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "Quest2 runtime review plan") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "student_artifact_bytes_reverified",
    "teacher_remains_visual_authority",
    "physical_device_installation_required",
    "physical_device_evidence_required",
    "human_runtime_visual_acceptance_required",
    "runtime_review_ready"
)) {
    if ($result.$field -isnot [bool] -or $result.$field -ne $true) {
        throw "Quest2 runtime review plan requirement missing: $field"
    }
}
foreach ($field in @(
    "student_fidelity_claim_exceeds_teacher",
    "physical_device_evidence_present",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($result.$field -isnot [bool] -or $result.$field -ne $false) {
        throw "Quest2 runtime review plan crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "Quest2 physical runtime review plan: READY"
Write-Host "Target device:                      $($result.target_device_model)"
Write-Host "Student representation:            $($result.student_representation)"
Write-Host "Student artifacts:                 $($result.student_artifact_count)"
Write-Host "Fidelity dimensions:               $($result.fidelity_delta_dimension_count)"
Write-Host "Physical device evidence:          FALSE"
Write-Host "Runtime acceptance:                FALSE"
Write-Host "Production:                        FALSE"
Write-Host "Plan: $outputPath"
exit 0
