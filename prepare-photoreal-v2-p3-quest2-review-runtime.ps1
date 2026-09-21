param(
    [Parameter(Mandatory = $true)][string]$FinalWorkspace,
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [string]$ReviewRuntimeWorkspace = "",
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
    throw "P3 Quest review-runtime materialization requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$FinalWorkspace = Need-Directory -Path $FinalWorkspace -Label "Final P3 workspace"
$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "P3 runtime-review workspace"
$finalOutput = Need-Directory -Path (Join-Path $FinalWorkspace "output") -Label "Final P3 output"
$runtimeReviewPlan = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "P3 runtime-review plan"

if ([string]::IsNullOrWhiteSpace($ReviewRuntimeWorkspace)) {
    $ReviewRuntimeWorkspace = Join-Path (Split-Path -Parent $RuntimeReviewWorkspace) "quest2-review-runtime"
} else {
    $ReviewRuntimeWorkspace = [System.IO.Path]::GetFullPath($ReviewRuntimeWorkspace)
}
if (Test-Path -LiteralPath $ReviewRuntimeWorkspace) {
    throw "P3 Quest review-runtime workspace already exists: $ReviewRuntimeWorkspace"
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - P3 QUEST REVIEW RUNTIME"
Write-Host "Revision:              $head"
Write-Host "Final P3 workspace:    $FinalWorkspace"
Write-Host "Runtime-review plan:   $runtimeReviewPlan"
Write-Host "Review workspace:      $ReviewRuntimeWorkspace"
Write-Host "Gate A / BodyPrint:    NOT USED"
Write-Host "Physical review only:  TRUE"
Write-Host "XR/stereo acceptance:  FALSE"
Write-Host "Photoreal acceptance:  FALSE"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_quest2_review_runtime",
    "--runtime-review-plan", $runtimeReviewPlan,
    "--final-output-root", $finalOutput,
    "--workspace", $ReviewRuntimeWorkspace,
    "--bodyrig-revision", $head
)
& $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "P3 Quest review-runtime materialization failed with exit code $LASTEXITCODE."
}

$manifest = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "p3-quest2-review-manifest.json") -Label "P3 Quest review manifest"
$receipt = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "p3-quest2-review-runtime-receipt.json") -Label "P3 Quest review-runtime receipt"
$avatar = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "avatar.vrm") -Label "P3 Quest review avatar"
$basecolor = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "basecolor.png") -Label "P3 Quest review basecolor"
$provenance = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "quest2-modular-provenance.json") -Label "P3 Quest review provenance"

$result = Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$result.format -ne "bodyrig-photoreal-p3-quest2-review-runtime-workspace" -or
    $result.artifact_bytes_verified_by_core -ne $true -or
    $result.physical_review_only -ne $true -or
    $result.comparison_only -ne $true -or
    $result.physical_device_evidence_present -ne $false -or
    $result.runtime_acceptance_authority -ne $false -or
    $result.photoreal_acceptance_authority -ne $false -or
    $result.production_activation -ne $false
) {
    throw "P3 Quest review-runtime receipt crossed its review-only authority boundary."
}

Write-Host ""
Write-Host "P3 Quest review runtime: READY"
Write-Host "Manifest:              $manifest"
Write-Host "Avatar:                $avatar"
Write-Host "Basecolor:             $basecolor"
Write-Host "Provenance:            $provenance"
Write-Host "Receipt:               $receipt"
Write-Host "Gate A authority:      NONE"
Write-Host "XR/stereo acceptance:  FALSE"
Write-Host "Production:            FALSE"
exit 0
