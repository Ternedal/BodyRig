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
        throw "V5 review completed without convergence decision evidence."
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
        throw "V5 review completed without silhouette diagnostic evidence."
    }
}

Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead

$scoreSpecs = @(
    @{ Label = "baseline"; File = "iteration-01-baseline.json" },
    @{ Label = "refit1"; File = "iteration-02-refit1.json" },
    @{ Label = "reconstruction2"; File = "iteration-03-reconstruction2.json" }
)
$scoreRows = foreach ($spec in $scoreSpecs) {
    $evaluation = Get-Content -LiteralPath (Join-Path $reanalysisOutput $spec.File) -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{
        Candidate = $spec.Label
        Overall = $evaluation.measurement.scores.overall
        Body = $evaluation.measurement.scores.body_silhouette
        Face = $evaluation.measurement.scores.face_appearance
        Hair = $evaluation.measurement.scores.hair_appearance
        Skin = $evaluation.measurement.scores.skin_material
        Photo = $evaluation.measurement.scores.photorealism
        Plausible = $evaluation.measurement.scores.human_plausibility
        HeadShoulder = $evaluation.plausibility.head_shoulder_ratio
    }
}

$diagnosticRows = foreach ($label in @("baseline", "refit1", "reconstruction2")) {
    $report = Get-Content -LiteralPath (Join-Path $diagnosticOutput "$label\silhouette-diagnostic.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{
        Candidate = $label
        Similarity = $report.profile_similarity
        HeadShoulder = $report.candidate.head_shoulder_ratio
        Foreground = $report.candidate.mask.foreground_fraction
        BBoxAspect = $report.candidate.mask.bbox_aspect_width_over_height
        BBoxFill = $report.candidate.mask.bbox_fill_fraction
    }
}

$decision = Get-Content -LiteralPath (Join-Path $reanalysisOutput "convergence-decision.json") -Raw -Encoding UTF8 | ConvertFrom-Json

Write-Host ""
Write-Host "============================================================"
Write-Host "BODYRIG V5 REVIEW COMPLETE"
Write-Host "Revision:    $pinnedHead"
Write-Host "Reanalysis:  $reanalysisOutput"
Write-Host "Diagnostics: $diagnosticOutput"
Write-Host ""
Write-Host "V5 scores"
$scoreRows | Format-Table -AutoSize
Write-Host ""
Write-Host "Silhouette diagnostics"
$diagnosticRows | Format-Table -AutoSize
Write-Host ""
Write-Host "Best iteration: $($decision.best_iteration)"
Write-Host "Best overall:   $($decision.best_overall)"
Write-Host "State:          $($decision.state)"
Write-Host "Strategy:       $($decision.strategy)"
Write-Host "Next focus:     $($decision.next_focus)"
Write-Host "============================================================"
