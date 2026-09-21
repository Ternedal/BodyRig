param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [string]$MachinePrefill = "",
    [string]$Output = "",
    [Parameter(Mandatory = $true)][string]$ReviewedBy,
    [Parameter(Mandatory = $true)][string]$ReviewNotes,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$IdentityLikeness,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$FaceDetail,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$Eyes,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$HairSilhouetteAndAppearance,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$SkinMaterialResponse,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$HandsAndExtremities,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$MotionIdentityPreservation,
    [Parameter(Mandatory = $true)][ValidateSet("pass", "fail")][string]$TemporalStability,
    [Parameter(Mandatory = $true)][switch]$ConfirmPhysicalDeviceReviewComplete,
    [switch]$ReuseExisting,
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
    param([string]$Requested, [string]$RepoRoot)
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
    throw "Quest2 guided human review requires an exact clean BodyRig checkout."
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

if ([string]::IsNullOrWhiteSpace($MachinePrefill)) {
    $MachinePrefill = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.machine-prefill.json"
}
$MachinePrefill = Need-File -Path $MachinePrefill -Label "machine-safe Quest2 physical review prefill"

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.reviewed.json"
} else {
    $Output = [IO.Path]::GetFullPath($Output)
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 GUIDED HUMAN REVIEW"
Write-Host "Revision:             $head"
Write-Host "Runtime review plan:  $plan"
Write-Host "Machine prefill:      $MachinePrefill"
Write-Host "Reviewer:             $ReviewedBy"
Write-Host "Decisions:            8 explicit PASS/FAIL"
Write-Host "Output:               $Output"
Write-Host "Production:           FALSE"
Write-Host "============================================================"

$arguments = @(
    "-m", "bodyrig.photoreal_p3_guided_human_review",
    "--runtime-review-plan", $plan,
    "--machine-prefill", $MachinePrefill,
    "--out", $Output,
    "--reviewed-by", $ReviewedBy,
    "--review-notes", $ReviewNotes,
    "--decision", "identity_likeness=$IdentityLikeness",
    "--decision", "face_detail=$FaceDetail",
    "--decision", "eyes=$Eyes",
    "--decision", "hair_silhouette_and_appearance=$HairSilhouetteAndAppearance",
    "--decision", "skin_material_response=$SkinMaterialResponse",
    "--decision", "hands_and_extremities=$HandsAndExtremities",
    "--decision", "motion_identity_preservation=$MotionIdentityPreservation",
    "--decision", "temporal_stability=$TemporalStability",
    "--confirm-physical-device-review-complete"
)
if ($ReuseExisting) {
    $arguments += "--reuse-existing"
}

$outputLines = @(& $python @arguments 2>&1)
$code = $LASTEXITCODE
foreach ($line in $outputLines) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Quest2 guided human review failed with exit code $code."
}

$reviewed = Get-Content -LiteralPath (Need-File -Path $Output -Label "reviewed Quest2 physical evidence") -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    $reviewed.operator_supplied -isnot [bool] -or
    $reviewed.operator_supplied -ne $true -or
    $reviewed.physical_device_observed -isnot [bool] -or
    $reviewed.physical_device_observed -ne $true -or
    $reviewed.confirm_physical_device_review_complete -isnot [bool] -or
    $reviewed.confirm_physical_device_review_complete -ne $true
) {
    throw "Guided human review output did not preserve the required physical/operator boundary."
}
foreach ($item in @($reviewed.visual_results)) {
    if ([string]$item.decision -notin @("pass", "fail")) {
        throw "Guided human review output contains a non-final visual decision."
    }
}

Write-Host ""
Write-Host "Guided human review evidence: COMPLETE"
Write-Host "Final authority:              NOT YET RECORDED"
Write-Host "Production activation:        FALSE"
Write-Host "Reviewed evidence:            $Output"
Write-Host ""
Write-Host "Next command:"
Write-Host ".\record-photoreal-v2-p3-quest2-physical-runtime-review.ps1 -RuntimeReviewWorkspace `"$RuntimeReviewWorkspace`" -Evidence `"$Output`""
exit 0
