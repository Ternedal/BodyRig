param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$BodyRigPython = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
Set-Location $repoRoot
$WorkRoot = (Resolve-Path -LiteralPath $WorkRoot).Path

$reanalysis = Join-Path $repoRoot "run-fidelity-v5-reanalysis.ps1"
$diagnostics = Join-Path $repoRoot "run-fidelity-silhouette-diagnostics.ps1"
foreach ($script in @($reanalysis, $diagnostics)) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw "Required fidelity review script not found: $script"
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG V5 REVIEW - EXISTING RENDERS ONLY"
Write-Host "No Unity render and no SiTH reconstruction will be started."
Write-Host "============================================================"

Write-Host ""
Write-Host "=== 1/2 V5 FIDELITY REANALYSIS ==="
& $reanalysis -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython

Write-Host ""
Write-Host "=== 2/2 SILHOUETTE MASK/PROFILE DIAGNOSTICS ==="
& $diagnostics -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve BodyRig Git HEAD after fidelity review."
}
$tag = $head.Substring(0, 8)
$reanalysisOutput = Join-Path $WorkRoot "reanalysis-v5-$tag"
$diagnosticOutput = Join-Path $WorkRoot "silhouette-diagnostics-$tag"

if (-not (Test-Path -LiteralPath (Join-Path $reanalysisOutput "convergence-decision.json") -PathType Leaf)) {
    throw "V5 review completed without convergence decision evidence."
}
if (-not (Test-Path -LiteralPath $diagnosticOutput -PathType Container)) {
    throw "V5 review completed without silhouette diagnostic evidence."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG V5 REVIEW COMPLETE"
Write-Host "Reanalysis:  $reanalysisOutput"
Write-Host "Diagnostics: $diagnosticOutput"
Write-Host "============================================================"
