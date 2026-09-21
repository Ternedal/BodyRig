param(
    [Parameter(Mandatory = $true)][string]$TeacherWorkRoot,
    [string]$P3Root = "",
    [switch]$ReplaceExisting,
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
    throw "P3 Quest runtime materialization requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 Quest runtime materialization requires an exact clean BodyRig checkout."
}

$TeacherWorkRoot = Need-Directory -Path $TeacherWorkRoot -Label "Teacher work root"
if ([string]::IsNullOrWhiteSpace($P3Root)) {
    $P3Root = Join-Path $TeacherWorkRoot "p3-device-distillation"
}
$P3Root = Need-Directory -Path $P3Root -Label "P3 work root"
$executionRoot = Need-Directory -Path (Join-Path $P3Root "execution") -Label "P3 distillation execution root"
$receipt = Need-File -Path (Join-Path $executionRoot "p3-device-distillation-execution-receipt.json") -Label "P3 distillation execution receipt"
$studentOutput = Need-Directory -Path (Join-Path $executionRoot "output") -Label "P3 student output root"
$runtimeRoot = Join-Path $P3Root "quest-runtime"

if (Test-Path -LiteralPath $runtimeRoot) {
    if (-not $ReplaceExisting) {
        throw "P3 Quest runtime already exists: $runtimeRoot"
    }
    Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
}

$Python = Resolve-BodyRigPython -Requested $BodyRigPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - MATERIALIZE QUEST2 RUNTIME"
Write-Host "Execution receipt:      $receipt"
Write-Host "Student output:         $studentOutput"
Write-Host "Runtime output:         $runtimeRoot"
Write-Host "Loader contract:        bodyrig-runtime-assets-v1"
Write-Host "Student bytes:          REVERIFY BEFORE COPY"
Write-Host "Runtime bytes:          REVERIFY AFTER COPY"
Write-Host "Physical review:        REQUIRED"
Write-Host "Photoreal acceptance:   FALSE"
Write-Host "Production:             FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_quest_runtime_package",
    "--execution-receipt", $receipt,
    "--student-output-root", $studentOutput,
    "--out", $runtimeRoot
)
$output = @(& $Python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Host ([string]$line) }
if ($code -ne 0) {
    throw "P3 Quest runtime materialization failed with code $code."
}

$manifest = Get-Content -LiteralPath (Need-File -Path (Join-Path $runtimeRoot "runtime-manifest.json") -Label "Quest runtime manifest") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$packageReceipt = Get-Content -LiteralPath (Need-File -Path (Join-Path $runtimeRoot "p3-quest-runtime-package-receipt.json") -Label "Quest runtime package receipt") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if ([string]$manifest.format -ne "bodyrig-runtime-assets" -or $manifest.version -is [bool] -or [double]$manifest.version -ne 1.0) {
    throw "Quest runtime manifest does not match the reference-renderer loader contract."
}
foreach ($field in @(
    "student_bytes_reverified_before_copy",
    "runtime_bytes_reverified_after_copy",
    "physical_device_review_required"
)) {
    if ($packageReceipt.$field -isnot [bool] -or $packageReceipt.$field -ne $true) {
        throw "P3 Quest runtime package requirement missing: $field"
    }
}
foreach ($field in @(
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($packageReceipt.$field -isnot [bool] -or $packageReceipt.$field -ne $false) {
        throw "P3 Quest runtime package crossed authority boundary: $field"
    }
}

Write-Host ""
Write-Host "P3 Quest2 runtime: MATERIALIZED"
Write-Host "Package SHA:       $($packageReceipt.runtime_package_sha256)"
Write-Host "Avatar SHA:        $($packageReceipt.runtime_avatar_sha256)"
Write-Host "Manifest SHA:      $($packageReceipt.runtime_manifest_sha256)"
Write-Host "Physical review:   REQUIRED"
Write-Host "Photoreal:         FALSE"
Write-Host "Production:        FALSE"
Write-Host "Runtime: $runtimeRoot"
exit 0
