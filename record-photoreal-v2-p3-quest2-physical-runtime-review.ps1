param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$Evidence,
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
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
    throw "Quest2 physical runtime review requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "Quest2 runtime review workspace"
$plan = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"
$Evidence = Need-File -Path $Evidence -Label "Quest2 physical runtime evidence"
$outputPath = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-review.json"
if (Test-Path -LiteralPath $outputPath) {
    throw "Quest2 physical runtime review receipt already exists: $outputPath"
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

$evidenceJson = Get-Content -LiteralPath $Evidence -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ([string]$evidenceJson.format -ne "bodyrig-photoreal-p3-physical-runtime-evidence") {
    throw "Quest2 physical runtime evidence format mismatch."
}
foreach ($field in @(
    "operator_supplied",
    "physical_device_observed",
    "confirm_physical_device_review_complete"
)) {
    if ($evidenceJson.$field -isnot [bool] -or $evidenceJson.$field -ne $true) {
        throw "Quest2 physical runtime evidence requirement missing: $field"
    }
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 PHYSICAL PASS/FAIL"
Write-Host "Revision:               $head"
Write-Host "Runtime review plan:    $plan"
Write-Host "Evidence:               $Evidence"
Write-Host "Physical device seen:   TRUE"
Write-Host "Target device:          $($evidenceJson.target_device_model)"
Write-Host "Visual decisions:       $($evidenceJson.visual_results.Count)"
Write-Host "Observed refresh:       $($evidenceJson.observed_refresh_hz) Hz"
Write-Host "P95 frame time:         $($evidenceJson.p95_frame_time_ms) ms"
Write-Host "Installed hashes seen:  $($evidenceJson.installed_student_artifacts.Count)"
Write-Host "Production:             FALSE regardless of PASS/FAIL"
Write-Host "============================================================"

$argsList = @(
    "-m", "bodyrig.photoreal_p3_physical_runtime_review",
    "--runtime-review-plan", $plan,
    "--evidence", $Evidence,
    "--out", $outputPath
)
$output = @(& $python @argsList 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Quest2 physical runtime review failed with code $code."
}

$receipt = Get-Content -LiteralPath (Need-File -Path $outputPath -Label "Quest2 physical runtime review receipt") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    $receipt.physical_device_evidence_present -isnot [bool] -or
    $receipt.physical_device_evidence_present -ne $true
) {
    throw "Quest2 physical runtime review did not persist physical device evidence."
}
if (
    $receipt.physical_device_review_complete -isnot [bool] -or
    $receipt.physical_device_review_complete -ne $true
) {
    throw "Quest2 physical runtime review is incomplete."
}
if (
    $receipt.production_activation -isnot [bool] -or
    $receipt.production_activation -ne $false
) {
    throw "Quest2 physical runtime review crossed production authority."
}

$status = ([string]$receipt.runtime_review_status).ToLowerInvariant()
if ($status -eq "pass") {
    foreach ($field in @(
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority"
    )) {
        if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $true) {
            throw "Quest2 physical PASS authority missing: $field"
        }
    }
} elseif ($status -eq "fail") {
    foreach ($field in @(
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority"
    )) {
        if ($receipt.$field -isnot [bool] -or $receipt.$field -ne $false) {
            throw "Quest2 physical FAIL unexpectedly grants authority: $field"
        }
    }
} else {
    throw "Quest2 physical runtime review status is invalid: $status"
}

Write-Host ""
Write-Host "Quest2 physical review:       $($status.ToUpperInvariant())"
Write-Host "Runtime acceptance:           $($receipt.runtime_acceptance_authority)"
Write-Host "Photoreal acceptance:         $($receipt.photoreal_acceptance_authority)"
Write-Host "Production activation:        FALSE"
Write-Host "Receipt: $outputPath"
exit 0
