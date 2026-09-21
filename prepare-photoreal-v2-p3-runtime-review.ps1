param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P3Root = "",
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
    throw "P3 physical runtime review planning requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 physical runtime review planning requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P3Root)) {
    $P3Root = Join-Path $TeacherWorkRoot "p3-device-distillation"
}
$P3Root = Need-Directory -Path $P3Root -Label "P3 work root"

$plan = Need-File -Path (Join-Path $P3Root "p3-device-distillation-plan.json") -Label "P3 distillation plan"
$executionRoot = Need-Directory -Path (Join-Path $P3Root "execution") -Label "P3 distillation execution root"
$receipt = Need-File -Path (Join-Path $executionRoot "p3-device-distillation-execution-receipt.json") -Label "P3 distillation execution receipt"
$studentOutput = Need-Directory -Path (Join-Path $executionRoot "output") -Label "P3 student output root"
$reviewRoot = Join-Path $P3Root "runtime-review"
New-Item -ItemType Directory -Path $reviewRoot -Force | Out-Null
$outputPath = Join-Path $reviewRoot "p3-device-runtime-review-plan.json"

if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P3 runtime review plan already exists: $outputPath"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P3 PHYSICAL RUNTIME REVIEW PLAN"
Write-Host "Distillation plan:       $plan"
Write-Host "Execution receipt:       $receipt"
Write-Host "Student output:          $studentOutput"
Write-Host "Student bytes:           REVERIFY NOW"
Write-Host "Physical device install: REQUIRED"
Write-Host "Physical evidence:       NOT PRESENT"
Write-Host "Human runtime review:    REQUIRED"
Write-Host "Runtime acceptance:      FALSE"
Write-Host "Photoreal acceptance:    FALSE"
Write-Host "Production:              FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_device_runtime_review_plan",
    "--plan", $plan,
    "--execution-receipt", $receipt,
    "--student-output-root", $studentOutput,
    "--out", $outputPath
)
if ($ReuseExisting) { $argsList += "--reuse-existing" }

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P3 physical runtime review planning failed with code $code."
}

$result = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P3 runtime review plan") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "student_artifact_bytes_reverified",
    "teacher_remains_visual_authority",
    "physical_device_installation_required",
    "physical_device_evidence_required",
    "human_runtime_visual_acceptance_required",
    "runtime_review_ready"
)) {
    if ($result.$field -isnot [bool] -or $result.$field -ne $true) {
        throw "P3 runtime review plan requirement missing: $field"
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
        throw "P3 runtime review plan crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P3 physical runtime review plan: READY"
Write-Host "Target device:                    $($result.target_device_model)"
Write-Host "Student representation:          $($result.student_representation)"
Write-Host "Student components:              $($result.student_components -join ', ')"
Write-Host "Student artifacts:               $($result.student_artifact_count)"
Write-Host "Fidelity deltas:                 $($result.fidelity_delta_dimension_count)"
Write-Host "Physical device evidence:        FALSE"
Write-Host "Runtime acceptance:              FALSE"
Write-Host "Production:                      FALSE"
Write-Host "Plan: $outputPath"
exit 0
