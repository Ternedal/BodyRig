param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$BodyRigPython = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Head {
    param([string]$RepoRoot)
    $head = (& git -C $RepoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
        throw "Could not resolve BodyRig Git HEAD."
    }
    return $head
}

function Assert-HeadPinned {
    param([string]$RepoRoot,[string]$Expected)
    $actual = Get-Head -RepoRoot $RepoRoot
    if ($actual -ne $Expected) {
        throw "BodyRig checkout changed during fidelity review: expected $Expected, found $actual"
    }
}

function Test-ReanalysisComplete {
    param([string]$Path)
    $required = @(
        "iteration-01-baseline.json",
        "iteration-02-refit1.json",
        "iteration-03-reconstruction2.json",
        "convergence-decision.json"
    )
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $name) -PathType Leaf)) { return $false }
    }
    return $true
}

function Test-DiagnosticsComplete {
    param([string]$Path)
    foreach ($label in @("baseline", "refit1", "reconstruction2")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path "$label\silhouette-diagnostic.json") -PathType Leaf)) { return $false }
    }
    return $true
}

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

$pinnedHead = Get-Head -RepoRoot $repoRoot
$tag = $pinnedHead.Substring(0, 8)
$reanalysisOutput = Join-Path $WorkRoot "reanalysis-v5-$tag"
$diagnosticOutput = Join-Path $WorkRoot "silhouette-diagnostics-$tag"

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG V5 REVIEW - EXISTING RENDERS ONLY"
Write-Host "Revision: $pinnedHead"
Write-Host "No Unity render and no SiTH reconstruction will be started."
Write-Host "============================================================"

Write-Host ""
Write-Host "=== 1/2 V5 FIDELITY REANALYSIS ==="
if (Test-ReanalysisComplete -Path $reanalysisOutput) {
    Write-Host "Reusing complete v5 reanalysis: $reanalysisOutput"
} else {
    if (Test-Path -LiteralPath $reanalysisOutput) {
        Write-Host "Removing incomplete cheap reanalysis output: $reanalysisOutput"
        Remove-Item -LiteralPath $reanalysisOutput -Recurse -Force
    }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead
    & $reanalysis -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead
    if (-not (Test-ReanalysisComplete -Path $reanalysisOutput)) {
        throw "V5 reanalysis returned without complete evidence."
    }
}

Write-Host ""
Write-Host "=== 2/2 SILHOUETTE MASK/PROFILE DIAGNOSTICS ==="
if (Test-DiagnosticsComplete -Path $diagnosticOutput) {
    Write-Host "Reusing complete silhouette diagnostics: $diagnosticOutput"
} else {
    if (Test-Path -LiteralPath $diagnosticOutput) {
        Write-Host "Removing incomplete cheap diagnostic output: $diagnosticOutput"
        Remove-Item -LiteralPath $diagnosticOutput -Recurse -Force
    }
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead
    & $diagnostics -WorkRoot $WorkRoot -BodyRigPython $BodyRigPython
    Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead
    if (-not (Test-DiagnosticsComplete -Path $diagnosticOutput)) {
        throw "Silhouette diagnostics returned without complete evidence."
    }
}

Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG V5 REVIEW COMPLETE"
Write-Host "Revision:    $pinnedHead"
Write-Host "Reanalysis:  $reanalysisOutput"
Write-Host "Diagnostics: $diagnosticOutput"
Write-Host "============================================================"
