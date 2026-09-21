param(
    [Parameter(Mandatory = $true)][string]$P0Root,
    [string]$WorkRoot = "",
    [string]$BodyRigPython = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-Python {
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

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)][string]$WindowsPath,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python
    )
    $code = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(& $Python -c $code $RepoRoot $WslExe $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not translate BodyRig path into WSL: $WindowsPath | $($lines -join ' ')"
    }
    try {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(([string]$lines[0]).Trim()))
    } catch {
        throw "BodyRig WSL path conversion returned invalid encoded data: $WindowsPath"
    }
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL path conversion returned invalid path: $WindowsPath"
    }
    return $value
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branch = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $branch.Count -ne 1 -or ([string]$branch[0]).Trim() -ne "main") {
    throw "Appearance epoch visual review requires the main branch."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Appearance epoch visual review requires an exact clean BodyRig checkout."
}
$head = ([string](& git -C $repoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig HEAD."
}

$P0Root = Need-Directory -Path $P0Root -Label "P0 root"
$datasetPlan = Need-File -Path (Join-Path $P0Root "dataset-plan.json") -Label "P0 dataset plan"
$sourceReceipt = Need-File -Path (Join-Path $P0Root "source-receipt.json") -Label "P0 source receipt"
$scanPlan = Need-File -Path (Join-Path $P0Root "scan-plan.json") -Label "P0 scan plan"
$frameIndex = Need-File -Path (Join-Path $P0Root "frame-index.json") -Label "P0 frame index"
$statusPath = Need-File -Path (Join-Path $P0Root "p0-status.json") -Label "P0 status"
$status = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ([string]$status.status -ne "teacher-training-authorized" -or $status.teacher_training_authorized -isnot [bool] -or $status.teacher_training_authorized -ne $true) {
    throw "P0 status does not authorize teacher training."
}
if ($status.photoreal_acceptance_authority -isnot [bool] -or $status.photoreal_acceptance_authority -ne $false) {
    throw "P0 status crossed photoreal acceptance authority."
}
if ($status.production_activation -isnot [bool] -or $status.production_activation -ne $false) {
    throw "P0 status crossed production authority."
}

if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = "$P0Root-teacher"
}
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

$Python = Resolve-Python -Requested $BodyRigPython -RepoRoot $repoRoot
$pathMap = Join-Path $WorkRoot "appearance-epoch-runtime-path-map.json"
$frameDigest = ([string](Get-FileHash -LiteralPath $frameIndex -Algorithm SHA256).Hash).ToLowerInvariant()
$reviewRoot = Join-Path $WorkRoot ("appearance-epoch-visual-review-{0}-{1}" -f $frameDigest.Substring(0,12), $head.Substring(0,8))

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - APPEARANCE EPOCH VISUAL REVIEW PREP"
Write-Host "Revision:        $head"
Write-Host "P0 root:         $P0Root"
Write-Host "Review root:     $reviewRoot"
Write-Host "Source rehash:   NO"
Write-Host "Frame replay:    EXACT P0 AUTHORIZED OBSERVATIONS ONLY"
Write-Host "Human review:    REQUIRED"
Write-Host "Teacher input:   FALSE"
Write-Host "Photoreal auth:  FALSE"
Write-Host "Production:      FALSE"
Write-Host "============================================================"
Write-Host ""

$oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$separator = [IO.Path]::PathSeparator
$newPythonPath = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) { $repoRoot } else { "$repoRoot$separator$oldPythonPath" }
[Environment]::SetEnvironmentVariable("PYTHONPATH", $newPythonPath, "Process")
try {
    Write-Host "=== 1/2 BUILD / REVALIDATE PRIVATE WSL PATH MAP ==="
    & $Python -m bodyrig.photoreal_appearance_epoch_visual_review path-map --dataset-plan $datasetPlan --source-receipt $sourceReceipt --scan-plan $scanPlan --frame-index $frameIndex --wsl-exe $WslExe --distribution $Distribution --out $pathMap
    if ($LASTEXITCODE -ne 0) { throw "Appearance epoch runtime path-map preparation failed with code $LASTEXITCODE." }
} finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
}

$pathMap = Need-File -Path $pathMap -Label "Appearance epoch runtime path map"
$wslRepo = Convert-ToWslPath -WindowsPath $repoRoot -RepoRoot $repoRoot -Python $Python
$wslPlan = Convert-ToWslPath -WindowsPath $datasetPlan -RepoRoot $repoRoot -Python $Python
$wslReceipt = Convert-ToWslPath -WindowsPath $sourceReceipt -RepoRoot $repoRoot -Python $Python
$wslScanPlan = Convert-ToWslPath -WindowsPath $scanPlan -RepoRoot $repoRoot -Python $Python
$wslFrameIndex = Convert-ToWslPath -WindowsPath $frameIndex -RepoRoot $repoRoot -Python $Python
$wslPathMap = Convert-ToWslPath -WindowsPath $pathMap -RepoRoot $repoRoot -Python $Python
$wslReviewRoot = Convert-ToWslPath -WindowsPath $reviewRoot -RepoRoot $repoRoot -Python $Python

& $WslExe -d $Distribution -- /usr/bin/test -x $LinuxPython 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Photoreal Linux Python is missing/not executable: $LinuxPython"
}

Write-Host ""
Write-Host "=== 2/2 REPLAY EXACT AUTHORIZED FRAMES + BUILD REVIEW HTML ==="
$wslArgs = @(
    "-d", $Distribution, "--", "/usr/bin/env",
    "PYTHONPATH=$wslRepo",
    "PYTHONNOUSERSITE=1",
    $LinuxPython,
    "-m", "bodyrig.photoreal_appearance_epoch_visual_review",
    "prepare",
    "--dataset-plan", $wslPlan,
    "--source-receipt", $wslReceipt,
    "--scan-plan", $wslScanPlan,
    "--frame-index", $wslFrameIndex,
    "--runtime-path-map", $wslPathMap,
    "--bodyrig-revision", $head,
    "--output-dir", $wslReviewRoot,
    "--reuse-existing"
)
& $WslExe @wslArgs
if ($LASTEXITCODE -ne 0) {
    throw "Appearance epoch visual review preparation failed with code $LASTEXITCODE."
}

$manifest = Need-File -Path (Join-Path $reviewRoot "appearance-epoch-visual-review-manifest.json") -Label "Appearance epoch visual review manifest"
$privateIndex = Need-File -Path (Join-Path $reviewRoot "private-review-index.json") -Label "Private appearance epoch review index"
$reviewIndex = Need-File -Path (Join-Path $reviewRoot "review-index.html") -Label "Appearance epoch review HTML"

$result = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
Write-Host ""
Write-Host "Appearance epoch visual review: READY"
Write-Host "Groups:            $($result.group_count)"
Write-Host "Train groups:      $($result.train_group_count)"
Write-Host "Evaluation groups: $($result.evaluation_group_count)"
Write-Host "Review frames:     $($result.eligible_observation_count)"
Write-Host "Exact frame SHA:   $($result.exact_p0_frame_hashes_reproduced)"
Write-Host "Source rehash:     $($result.source_media_rehash_performed)"
Write-Host "Review HTML:       $reviewIndex"
Write-Host "Manifest:          $manifest"
Write-Host "Private index:     $privateIndex"
Write-Host ""
Write-Host "Open manually when you are ready:"
Write-Host ('  Start-Process "' + $reviewIndex + '"')
Write-Host ""
Write-Host "This review pack grants NO teacher-input, photoreal or production authority."
