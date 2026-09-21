param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [string]$Output = ""
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

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "Quest2 runtime review workspace"
$planPath = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"
$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.template.json"
} else {
    $Output = [System.IO.Path]::GetFullPath($Output)
}
if (Test-Path -LiteralPath $Output) {
    throw "Quest2 physical evidence template already exists: $Output"
}

$visual = @()
foreach ($measurement in @($plan.fidelity_delta_measurements)) {
    $visual += [ordered]@{
        criterion = [string]$measurement.dimension
        decision = "REVIEW_REQUIRED"
    }
}

$installed = @()
foreach ($artifact in @($plan.student_artifacts)) {
    $installed += [ordered]@{
        relative_path = [string]$artifact.relative_path
        sha256 = [string]$artifact.sha256
    }
}

$template = [ordered]@{
    format = "bodyrig-photoreal-p3-physical-runtime-evidence"
    version = 1
    operator_supplied = $true
    runtime_review_plan_sha256 = [string]$plan.p3_device_runtime_review_plan_sha256
    target_device_family = [string]$plan.target_device_family
    target_device_model = [string]$plan.target_device_model
    physical_device_observed = $false
    installed_student_artifacts = $installed
    observed_refresh_hz = $null
    p95_frame_time_ms = $null
    stereo_rendering_observed = $false
    vr_safe_frame_pacing_observed = $false
    installed_student_hashes_verified_on_device = $false
    visual_results = $visual
    reviewed_by = "REVIEW_REQUIRED"
    review_notes = "REVIEW_REQUIRED"
    confirm_physical_device_review_complete = $false
}

$template | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Output -Encoding UTF8

Write-Host "Quest2 physical evidence template created:"
Write-Host $Output
Write-Host ""
Write-Host "This file is intentionally NOT valid review evidence yet."
Write-Host "After the real headset review, replace every REVIEW_REQUIRED value,"
Write-Host "record measured refresh/p95 frame time, verify hashes on-device,"
Write-Host "set physical_device_observed=true, and only then set"
Write-Host "confirm_physical_device_review_complete=true."
exit 0
