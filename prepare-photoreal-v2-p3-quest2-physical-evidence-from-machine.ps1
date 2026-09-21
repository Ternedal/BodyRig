param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$MachineProbe,
    [string]$Output = "",
    [switch]$ReuseExisting
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

function Need-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') {
        throw "$Label is not a canonical SHA-256."
    }
    return $normalized
}

function Need-PositiveFinite {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -is [bool] -or $Value -isnot [ValueType]) {
        throw "$Label must be numeric."
    }
    $number = [double]$Value
    if ([double]::IsNaN($number) -or [double]::IsInfinity($number) -or $number -le 0) {
        throw "$Label must be finite and positive."
    }
    return $number
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Quest2 P3 physical evidence prefill requires an exact clean BodyRig checkout."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "Quest2 runtime review workspace"
$planPath = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "Quest2 runtime review plan"
$MachineProbe = Need-File -Path $MachineProbe -Label "Quest2 P3 machine probe"

$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$probe = Get-Content -LiteralPath $MachineProbe -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if (
    [string]$plan.format -ne "bodyrig-photoreal-p3-device-runtime-review-plan" -or
    $plan.version -is [bool] -or
    [double]$plan.version -ne 1.0
) {
    throw "Quest2 runtime review plan format/version mismatch."
}
if (
    [string]$probe.format -ne "bodyrig-photoreal-p3-quest2-machine-probe" -or
    $probe.version -is [bool] -or
    [double]$probe.version -ne 1.0
) {
    throw "Quest2 P3 machine probe format/version mismatch."
}

$planSha = Need-Sha256 -Value ([string]$plan.p3_device_runtime_review_plan_sha256) -Label "runtime review plan SHA-256"
$probePlanSha = Need-Sha256 -Value ([string]$probe.p3_device_runtime_review_plan_sha256) -Label "machine probe runtime review plan SHA-256"
if ($probePlanSha -ne $planSha) {
    throw "Quest2 P3 machine probe belongs to a different runtime review plan."
}
if (
    [string]$plan.target_device_family -ne "meta-quest" -or
    [string]$plan.target_device_model -ne "quest-2" -or
    [string]$probe.target_device_family -ne "meta-quest" -or
    [string]$probe.target_device_model -ne "quest-2"
) {
    throw "Quest2 P3 physical evidence prefill requires exact Quest 2 lineage."
}

foreach ($field in @(
    "installed_student_hashes_verified_on_device",
    "vrm10_loaded",
    "humanoid_valid",
    "required_bones_valid",
    "openxr_loader_active",
    "xr_device_active",
    "xr_display_running",
    "stereo_camera_active",
    "runtime_loaded",
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "human_runtime_visual_acceptance_required"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $true) {
        throw "Quest2 P3 machine proof is incomplete: $field"
    }
}
foreach ($field in @(
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $false) {
        throw "Quest2 P3 machine proof crossed human/production authority: $field"
    }
}
if ([string]$probe.stereo_authority -ne "unity-openxr-active-display-and-stereo-camera") {
    throw "Quest2 P3 machine proof has non-canonical stereo authority."
}
if ([string]$probe.stereo_rendering_mode -notin @("SinglePassInstanced", "SinglePassMultiview")) {
    throw "Quest2 P3 machine proof did not record a supported stereo rendering mode."
}
if ([int]$probe.eye_texture_width -le 0 -or [int]$probe.eye_texture_height -le 0) {
    throw "Quest2 P3 machine proof has invalid eye texture dimensions."
}

$targetRefresh = Need-PositiveFinite -Value $plan.target_profile.target_refresh_hz -Label "plan target refresh"
$maxFrameTime = Need-PositiveFinite -Value $plan.target_profile.max_frame_time_ms -Label "plan frame-time budget"
$probeTargetRefresh = Need-PositiveFinite -Value $probe.target_refresh_hz -Label "probe target refresh"
$probeMaxFrameTime = Need-PositiveFinite -Value $probe.max_frame_time_ms -Label "probe frame-time budget"
$observedRefresh = Need-PositiveFinite -Value $probe.observed_refresh_hz -Label "probe observed refresh"
$p95FrameTime = Need-PositiveFinite -Value $probe.p95_frame_time_ms -Label "probe p95 frame time"

if ($probeTargetRefresh -ne $targetRefresh -or $probeMaxFrameTime -ne $maxFrameTime) {
    throw "Quest2 P3 machine proof used a different performance budget from the runtime review plan."
}
if ($observedRefresh -lt $targetRefresh -or $p95FrameTime -gt $maxFrameTime) {
    throw "Quest2 P3 machine proof does not satisfy the runtime review performance budget."
}
if ([int]$probe.frame_time_sample_count -lt 120) {
    throw "Quest2 P3 machine proof contains too few frame-time samples."
}

$expectedArtifacts = @{}
foreach ($artifact in @($plan.student_artifacts)) {
    $relative = ([string]$artifact.relative_path).Replace("\", "/")
    if ([string]::IsNullOrWhiteSpace($relative) -or $expectedArtifacts.ContainsKey($relative)) {
        throw "Quest2 runtime review plan has an invalid/repeated student artifact."
    }
    $expectedArtifacts[$relative] = Need-Sha256 -Value ([string]$artifact.sha256) -Label "planned student artifact SHA-256"
}
if ($expectedArtifacts.Count -lt 1) {
    throw "Quest2 runtime review plan contains no student artifacts."
}

$installedArtifacts = @()
$seen = @{}
foreach ($artifact in @($probe.installed_student_artifacts)) {
    $relative = ([string]$artifact.relative_path).Replace("\", "/")
    if ([string]::IsNullOrWhiteSpace($relative) -or $seen.ContainsKey($relative)) {
        throw "Quest2 P3 machine proof has an invalid/repeated installed student artifact."
    }
    $sha = Need-Sha256 -Value ([string]$artifact.sha256) -Label "installed student artifact SHA-256"
    if (-not $expectedArtifacts.ContainsKey($relative) -or $expectedArtifacts[$relative] -ne $sha) {
        throw "Quest2 P3 machine proof installed bytes differ from the runtime review plan: $relative"
    }
    $seen[$relative] = $true
    $installedArtifacts += [ordered]@{
        relative_path = $relative
        sha256 = $sha
    }
}
if ($seen.Count -ne $expectedArtifacts.Count) {
    throw "Quest2 P3 machine proof omitted planned student artifacts."
}
foreach ($relative in $expectedArtifacts.Keys) {
    if (-not $seen.ContainsKey($relative)) {
        throw "Quest2 P3 machine proof omitted planned student artifact: $relative"
    }
}
$installedArtifacts = @($installedArtifacts | Sort-Object -Property relative_path)

$visual = @()
foreach ($measurement in @($plan.fidelity_delta_measurements)) {
    $dimension = ([string]$measurement.dimension).Trim()
    if ([string]::IsNullOrWhiteSpace($dimension)) {
        throw "Quest2 runtime review plan contains an invalid fidelity dimension."
    }
    $visual += [ordered]@{
        criterion = $dimension
        decision = "REVIEW_REQUIRED"
    }
}
if ($visual.Count -lt 1) {
    throw "Quest2 runtime review plan contains no fidelity dimensions."
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $RuntimeReviewWorkspace "p3-physical-runtime-evidence.machine-prefill.json"
} else {
    $Output = [IO.Path]::GetFullPath($Output)
}
$prefill = [ordered]@{
    format = "bodyrig-photoreal-p3-physical-runtime-evidence"
    version = 1

    # Deliberately FALSE. A human reviewer must explicitly set this to TRUE
    # only after completing the eight visual fidelity decisions below.
    operator_supplied = $false

    runtime_review_plan_sha256 = $planSha
    target_device_family = "meta-quest"
    target_device_model = "quest-2"

    # Safe to prefill from the device-generated machine probe.
    physical_device_observed = $true
    installed_student_artifacts = $installedArtifacts
    observed_refresh_hz = $observedRefresh
    p95_frame_time_ms = $p95FrameTime
    stereo_rendering_observed = $true
    vr_safe_frame_pacing_observed = $true
    installed_student_hashes_verified_on_device = $true

    # Never machine-filled with pass/fail.
    visual_results = $visual
    reviewed_by = "REVIEW_REQUIRED"
    review_notes = "Machine evidence prefilled from the exact Quest 2 OpenXR probe. Complete the eight visual decisions in-headset before confirmation."

    # Deliberately FALSE. The final recorder rejects the prefill until a
    # human has completed and explicitly confirmed the physical review.
    confirm_physical_device_review_complete = $false
}

if (Test-Path -LiteralPath $Output) {
    if (-not $ReuseExisting) {
        throw "Quest2 P3 physical evidence prefill already exists: $Output"
    }

    $existing = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $expectedCanonical = (
        $prefill |
            ConvertTo-Json -Depth 100 -Compress |
            ConvertFrom-Json -Depth 100 |
            ConvertTo-Json -Depth 100 -Compress
    )
    $existingCanonical = $existing | ConvertTo-Json -Depth 100 -Compress
    if ($existingCanonical -cne $expectedCanonical) {
        throw "Existing Quest2 P3 physical evidence prefill differs from the exact current runtime review plan and machine probe."
    }

    Write-Host "Existing machine-safe physical review prefill revalidated against the exact current plan/probe:"
    Write-Host $Output
    exit 0
}

$prefill | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Output -Encoding UTF8

Write-Host "============================================================"
Write-Host "BODYRIG P3 - QUEST2 PHYSICAL REVIEW PREFILL"
Write-Host "Runtime review plan:       $planPath"
Write-Host "Machine probe:             $MachineProbe"
Write-Host "Target:                    Quest 2 / OpenXR"
Write-Host "Observed refresh:          $observedRefresh Hz"
Write-Host "P95 frame time:            $p95FrameTime ms"
Write-Host "Installed hashes verified: TRUE"
Write-Host "Stereo runtime verified:   TRUE"
Write-Host "Human visual review:       REQUIRED"
Write-Host "Operator supplied:         FALSE"
Write-Host "Review confirmation:       FALSE"
Write-Host "============================================================"
Write-Host ""
Write-Host "Machine-safe physical review prefill created:"
Write-Host $Output
Write-Host ""
Write-Host "Before recording final evidence, a human must:"
Write-Host "  1. review every visual criterion in the Quest 2;"
Write-Host "  2. replace every REVIEW_REQUIRED decision with pass or fail;"
Write-Host "  3. replace reviewed_by with the reviewer identity;"
Write-Host "  4. edit review_notes if needed;"
Write-Host "  5. set operator_supplied=true;"
Write-Host "  6. set confirm_physical_device_review_complete=true."
Write-Host ""
Write-Host "Until then this file is intentionally rejected by the final review recorder."
exit 0
