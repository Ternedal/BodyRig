param(
    [Parameter(Mandatory = $true)][string]$PrimaryRepresentation,
    [string[]]$OptionalComponent = @(),
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
    throw "P3 student representation selection requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 student representation selection requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($P3Root)) {
    throw "Pass -P3Root pointing at the existing p3-device-distillation directory."
}
$P3Root = Need-Directory -Path $P3Root -Label "P3 device distillation root"
$planPath = Need-File -Path (Join-Path $P3Root "p3-device-distillation-plan.json") -Label "P3 device distillation plan"
$outputPath = Join-Path $P3Root "p3-student-representation-selection.json"

if ((Test-Path -LiteralPath $outputPath -PathType Leaf) -and -not $ReuseExisting) {
    throw "P3 student representation selection already exists: $outputPath"
}
$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P3 STUDENT REPRESENTATION"
Write-Host "P3 plan:                 $planPath"
Write-Host "Primary representation:  $PrimaryRepresentation"
Write-Host "Optional components:     $($OptionalComponent -join ', ')"
Write-Host "Student representation: SELECTED"
Write-Host "Distillation adapter:    NOT SELECTED"
Write-Host "Distillation run:        NOT STARTED"
Write-Host "Runtime acceptance:      FALSE"
Write-Host "Production:              FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_student_representation_selection",
    "--plan", $planPath,
    "--primary", $PrimaryRepresentation,
    "--out", $outputPath
)
foreach ($component in $OptionalComponent) {
    $argsList += @("--component", $component)
}
if ($ReuseExisting) { $argsList += "--reuse-existing" }

$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P3 student representation selection failed with code $code."
}

$receipt = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "P3 student representation selection") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
foreach ($field in @(
    "teacher_remains_visual_authority",
    "student_may_not_claim_fidelity_above_teacher",
    "fidelity_delta_measurement_required",
    "student_representation_selected",
    "distillation_adapter_required"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
        throw "P3 student representation selection authority missing: $field"
    }
}
foreach ($field in @(
    "distillation_adapter_selected",
    "distillation_job_start_authorized",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
        throw "P3 student representation selection crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P3 student representation: READY"
Write-Host "Target:                    $($receipt.target_model)"
Write-Host "Primary:                   $($receipt.primary_representation)"
Write-Host "Components:                $($receipt.optional_components -join ', ')"
Write-Host "Adapter:                   NOT SELECTED"
Write-Host "Distillation execution:    NOT STARTED"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Production:                FALSE"
Write-Host "Selection: $outputPath"
exit 0
