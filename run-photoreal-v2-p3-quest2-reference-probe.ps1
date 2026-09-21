param(
    [Parameter(Mandatory = $true)][string]$RuntimeReviewWorkspace,
    [Parameter(Mandatory = $true)][string]$StudentOutputRoot,
    [Parameter(Mandatory = $true)][string]$DeviceHandoffReceipt,
    [string]$ProbeWorkspace = "",
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "P3 Quest2 reference probe is Windows-orchestrated."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the P3 Quest2 reference probe."
}

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

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $value = $Value.Trim().ToLowerInvariant()
    if ($value -notmatch '^[0-9a-f]{64}$') {
        throw "$Label is not a canonical SHA-256."
    }
    return $value
}

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-Adb {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[switch]$Capture)
    $all = @()
    if (-not [string]::IsNullOrWhiteSpace($script:Serial)) {
        $all += @("-s", $script:Serial)
    }
    $all += $Arguments
    if ($Capture) {
        $lines = @(& $script:AdbExe @all 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "adb failed: $($lines -join [Environment]::NewLine)"
        }
        return $lines
    }
    & $script:AdbExe @all
    if ($LASTEXITCODE -ne 0) {
        throw "adb failed with exit code $LASTEXITCODE: $($Arguments -join ' ')"
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "P3 Quest2 reference probe requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$RuntimeReviewWorkspace = Need-Directory -Path $RuntimeReviewWorkspace -Label "P3 runtime review workspace"
$StudentOutputRoot = Need-Directory -Path $StudentOutputRoot -Label "Final P3 student output root"
$DeviceHandoffReceipt = Need-File -Path $DeviceHandoffReceipt -Label "P3 Quest2 device handoff receipt"
$planPath = Need-File -Path (Join-Path $RuntimeReviewWorkspace "p3-device-runtime-review-plan.json") -Label "P3 runtime review plan"

$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
$handoff = Get-Content -LiteralPath $DeviceHandoffReceipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if (
    [string]$plan.format -ne "bodyrig-photoreal-p3-device-runtime-review-plan" -or
    $plan.version -is [bool] -or
    [double]$plan.version -ne 1.0
) {
    throw "P3 runtime review plan format/version mismatch."
}
if (
    [string]$handoff.format -ne "bodyrig-photoreal-p3-quest2-device-handoff" -or
    $handoff.version -is [bool] -or
    [double]$handoff.version -ne 1.0
) {
    throw "P3 Quest2 device handoff receipt format/version mismatch."
}

$planSha = Need-Sha256 -Value ([string]$plan.p3_device_runtime_review_plan_sha256) -Label "P3 runtime review plan SHA-256"
if (
    (Need-Sha256 -Value ([string]$handoff.p3_device_runtime_review_plan_sha256) -Label "device handoff plan SHA-256") -ne $planSha -or
    [string]$plan.target_device_family -ne "meta-quest" -or
    [string]$plan.target_device_model -ne "quest-2" -or
    [string]$handoff.target_device_family -ne "meta-quest" -or
    [string]$handoff.target_device_model -ne "quest-2"
) {
    throw "P3 Quest2 reference probe plan/device lineage mismatch."
}
foreach ($field in @(
    "local_student_bytes_reverified",
    "physical_quest2_observed",
    "student_bytes_staged_to_device",
    "staged_student_hashes_roundtrip_verified"
)) {
    if ($handoff.$field -isnot [bool] -or $handoff.$field -ne $true) {
        throw "P3 Quest2 handoff proof is incomplete: $field"
    }
}
foreach ($field in @(
    "runtime_loaded",
    "installed_student_hashes_verified_on_device",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($handoff.$field -isnot [bool] -or $handoff.$field -ne $false) {
        throw "P3 Quest2 handoff crossed its staging-only authority boundary: $field"
    }
}

$planArtifacts = @($plan.student_artifacts)
if ($planArtifacts.Count -lt 1 -or [int]$plan.student_artifact_count -ne $planArtifacts.Count) {
    throw "P3 runtime review plan has an invalid student artifact universe."
}
$handoffArtifacts = @($handoff.student_artifacts)
if ($handoffArtifacts.Count -ne $planArtifacts.Count) {
    throw "P3 Quest2 handoff artifact count differs from runtime plan."
}

$handoffMap = @{}
foreach ($artifact in $handoffArtifacts) {
    $relative = ([string]$artifact.relative_path).Replace("\", "/")
    if ($handoffMap.ContainsKey($relative)) {
        throw "P3 Quest2 handoff repeats artifact: $relative"
    }
    $handoffMap[$relative] = Need-Sha256 -Value ([string]$artifact.sha256) -Label "handoff artifact SHA-256"
}

$normalizedArtifacts = @()
$avatarRelative = ""
foreach ($artifact in $planArtifacts) {
    $relative = ([string]$artifact.relative_path).Replace("\", "/")
    if (
        [string]::IsNullOrWhiteSpace($relative) -or
        $relative.StartsWith("/") -or
        $relative.StartsWith("../") -or
        ("/$relative/").Contains("/../")
    ) {
        throw "P3 runtime plan contains unsafe artifact path: $relative"
    }
    $sha = Need-Sha256 -Value ([string]$artifact.sha256) -Label "plan artifact SHA-256"
    if (-not $handoffMap.ContainsKey($relative) -or $handoffMap[$relative] -ne $sha) {
        throw "P3 Quest2 handoff artifact differs from runtime plan: $relative"
    }
    $windowsRelative = $relative.Replace("/", [IO.Path]::DirectorySeparatorChar)
    $localPath = Need-File -Path (Join-Path $StudentOutputRoot $windowsRelative) -Label "P3 student artifact"
    if ((Get-Item -LiteralPath $localPath).Length -ne [int64]$artifact.size_bytes -or (Sha256 $localPath) -ne $sha) {
        throw "P3 student artifact bytes drifted before Quest renderer probe: $relative"
    }
    if ([string]$artifact.kind -eq "student-runtime-package") {
        if (-not [string]::IsNullOrWhiteSpace($avatarRelative)) {
            throw "P3 runtime plan contains multiple student runtime packages."
        }
        $avatarRelative = $relative
    }
    $normalizedArtifacts += [ordered]@{
        kind = [string]$artifact.kind
        relative_path = $relative
        size_bytes = [int64]$artifact.size_bytes
        sha256 = $sha
        local_path = $localPath
    }
}
if ([string]::IsNullOrWhiteSpace($avatarRelative)) {
    throw "P3 runtime plan contains no student runtime package."
}

$contractPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\renderer-contract.json") -Label "Reference renderer contract"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$contract.format -ne "bodyrig-reference-renderer-contract" -or
    $contract.version -is [bool] -or
    [double]$contract.version -ne 1.0 -or
    [string]$contract.application_id -ne "dk.ternedal.bodyrig.reference"
) {
    throw "Reference renderer contract is not canonical."
}

$questXrContractPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\quest-xr-contract.json") -Label "Quest XR contract"
$questXr = Get-Content -LiteralPath $questXrContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$questXr.format -ne "bodyrig-reference-renderer-quest-xr-contract" -or
    $questXr.version -is [bool] -or
    [double]$questXr.version -ne 1.0 -or
    [string]$questXr.provider -ne "openxr" -or
    [string]$questXr.xr_management_package -ne "com.unity.xr.management" -or
    [string]$questXr.openxr_package -ne "com.unity.xr.openxr" -or
    [string]$questXr.target_platform -ne "android" -or
    [string]$questXr.target_device_family -ne "meta-quest" -or
    [string]$questXr.target_device_model -ne "quest-2" -or
    [string]$questXr.loader_type -ne "UnityEngine.XR.OpenXR.OpenXRLoader" -or
    [string]$questXr.render_mode -ne "single-pass-instanced" -or
    [string]$questXr.runtime_initialization -ne "xr-management" -or
    $questXr.production_activation -isnot [bool] -or
    $questXr.production_activation -ne $false
) {
    throw "Quest XR contract is not canonical."
}
$xrManagementVersion = ([string]$questXr.xr_management_version).Trim()
$openXrVersion = ([string]$questXr.openxr_version).Trim()
if ($xrManagementVersion -notmatch '^\d+\.\d+\.\d+ = [string]$contract.unity_editor_version
$pinnedAdb = Need-File -Path (Join-Path "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe") -Label "Pinned Unity Android adb"
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requestedAdb = Need-File -Path $AdbExe -Label "Requested adb"
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [StringComparison]::OrdinalIgnoreCase)) {
        throw "P3 Quest2 reference probe refuses non-pinned adb: $requestedAdb"
    }
}
$script:AdbExe = $pinnedAdb
$script:Serial = $Serial

if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(
        Invoke-Adb -Arguments @("devices") -Capture |
            Select-Object -Skip 1 |
            Where-Object { $_ -match '^\S+\s+device$' }
    )
    if ($devices.Count -ne 1) {
        throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached."
    }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(Quest\s*2|Oculus\s*Quest\s*2)') {
    throw "Connected adb device is not an exact Quest 2: '$model'"
}

if ([string]::IsNullOrWhiteSpace($ProbeWorkspace)) {
    $ProbeWorkspace = Join-Path $RuntimeReviewWorkspace "p3-quest2-reference-probe"
} else {
    $ProbeWorkspace = [IO.Path]::GetFullPath($ProbeWorkspace)
}
if (Test-Path -LiteralPath $ProbeWorkspace) {
    throw "P3 Quest2 reference probe workspace already exists: $ProbeWorkspace"
}
New-Item -ItemType Directory -Path $ProbeWorkspace | Out-Null
$ProbeWorkspace = Need-Directory -Path $ProbeWorkspace -Label "P3 Quest2 reference probe workspace"

$apk = Join-Path $repoRoot "reference-renderer\Builds\Quest\BodyRigReferenceProbe.apk"
$buildScript = Need-File -Path (Join-Path $repoRoot "reference-renderer\build-reference-renderer.ps1") -Label "Reference renderer build operator"
$buildArgs = @{
    Platform = "Quest"
    Output = $apk
}
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) {
    $buildArgs.UnityExe = $UnityExe
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 P3 REFERENCE PROBE"
Write-Host "Revision:                 $head"
Write-Host "Runtime review plan:      $planPath"
Write-Host "Device handoff:           $DeviceHandoffReceipt"
Write-Host "Quest device:             $model"
Write-Host "Artifacts:                $($normalizedArtifacts.Count)"
Write-Host "Renderer:                 canonical Unity/UniVRM reference project"
Write-Host "XR Management:            $xrManagementVersion"
Write-Host "OpenXR:                   $openXrVersion"
Write-Host "Target refresh:           $targetRefreshHz Hz"
Write-Host "Frame budget:             $maxFrameTimeMs ms"
Write-Host "Stereo machine evidence:  REQUIRED"
Write-Host "Production:               FALSE"
Write-Host "============================================================"

& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Reference renderer Quest build failed with exit code $LASTEXITCODE."
}
$apk = Need-File -Path $apk -Label "Reference renderer Quest APK"

$applicationId = [string]$contract.application_id
$remoteRoot = "/sdcard/Android/data/$applicationId/files/BodyRig/P3/current"
$remoteOutput = "$remoteRoot/output"
$remoteManifest = "$remoteRoot/p3-runtime-manifest.json"
$remoteRequest = "$remoteRoot/run-p3-probe.request"
$remoteProbe = "$remoteRoot/p3-quest2-machine-probe.json"

Invoke-Adb -Arguments @("install", "-r", $apk)
Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRoot' && mkdir -p '$remoteOutput'")

foreach ($artifact in $normalizedArtifacts) {
    $remotePath = "$remoteOutput/$([string]$artifact.relative_path)"
    $slash = $remotePath.LastIndexOf("/")
    $remoteParent = $remotePath.Substring(0, $slash)
    Invoke-Adb -Arguments @("shell", "mkdir", "-p", $remoteParent)
    Invoke-Adb -Arguments @("push", [string]$artifact.local_path, $remotePath)
}

$manifestPath = Join-Path $ProbeWorkspace "p3-runtime-manifest.json"
$manifestArtifacts = @(
    $normalizedArtifacts | ForEach-Object {
        [ordered]@{
            kind = [string]$_.kind
            relative_path = [string]$_.relative_path
            size_bytes = [int64]$_.size_bytes
            sha256 = [string]$_.sha256
        }
    }
)
$runtimeManifest = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-runtime"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    performer_id = [string]$plan.performer_id
    target_device_family = "meta-quest"
    target_device_model = "quest-2"
    target_refresh_hz = $targetRefreshHz
    max_frame_time_ms = $maxFrameTimeMs
    avatar_relative_path = $avatarRelative
    student_artifacts = $manifestArtifacts
}
$runtimeManifest | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Invoke-Adb -Arguments @("push", $manifestPath, $remoteManifest)
Invoke-Adb -Arguments @("shell", "touch", $remoteRequest)
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteProbe)
Invoke-Adb -Arguments @("shell", "monkey", "-p", $applicationId, "1")

$ready = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Seconds 1
    $state = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ]; then echo ready; fi") -Capture) -join "").Trim()
    if ($state -eq "ready") {
        $ready = $true
        break
    }
}
if (-not $ready) {
    throw "Quest 2 reference renderer did not produce P3 machine evidence. Inspect headset and adb logcat; request marker was preserved."
}

$probePath = Join-Path $ProbeWorkspace "p3-quest2-machine-probe.json"
Invoke-Adb -Arguments @("pull", $remoteProbe, $probePath)
$probePath = Need-File -Path $probePath -Label "P3 Quest2 machine probe"
$probe = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if (
    [string]$probe.format -ne "bodyrig-photoreal-p3-quest2-machine-probe" -or
    $probe.version -is [bool] -or
    [double]$probe.version -ne 1.0 -or
    [string]$probe.bodyrig_revision -ne $head -or
    (Need-Sha256 -Value ([string]$probe.p3_device_runtime_review_plan_sha256) -Label "probe plan SHA-256") -ne $planSha -or
    [string]$probe.target_device_family -ne "meta-quest" -or
    [string]$probe.target_device_model -ne "quest-2"
) {
    throw "Quest2 P3 machine probe lineage/format mismatch."
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
        throw "Quest2 P3 machine probe requirement missing: $field"
    }
}
foreach ($field in @(
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $false) {
        throw "Quest2 P3 machine probe crossed its v1 authority boundary: $field"
    }
}
if ([string]$probe.stereo_authority -ne "unity-openxr-active-display-and-stereo-camera") {
    throw "Quest2 P3 machine probe stereo authority is not canonical OpenXR evidence."
}
if (
    [int]$probe.eye_texture_width -le 0 -or
    [int]$probe.eye_texture_height -le 0 -or
    [string]$probe.stereo_rendering_mode -notin @("SinglePassInstanced", "SinglePassMultiview")
) {
    throw "Quest2 P3 machine probe did not prove a valid stereo eye-texture/rendering path."
}
if (
    [double]$probe.target_refresh_hz -ne $targetRefreshHz -or
    [double]$probe.max_frame_time_ms -ne $maxFrameTimeMs -or
    [double]$probe.observed_refresh_hz -lt $targetRefreshHz -or
    [double]$probe.p95_frame_time_ms -le 0 -or
    [double]$probe.p95_frame_time_ms -gt $maxFrameTimeMs -or
    [int]$probe.frame_time_sample_count -lt 120
) {
    throw "Quest2 P3 machine probe performance evidence does not satisfy the runtime-review target."
}

$installedMap = @{}
foreach ($item in @($probe.installed_student_artifacts)) {
    $installedMap[([string]$item.relative_path).Replace("\", "/")] = Need-Sha256 -Value ([string]$item.sha256) -Label "installed artifact SHA-256"
}
if ($installedMap.Count -ne $normalizedArtifacts.Count) {
    throw "Quest2 P3 machine probe installed artifact universe is incomplete."
}
foreach ($artifact in $normalizedArtifacts) {
    $relative = [string]$artifact.relative_path
    if (-not $installedMap.ContainsKey($relative) -or $installedMap[$relative] -ne [string]$artifact.sha256) {
        throw "Quest2 P3 machine probe installed bytes differ from P3 plan: $relative"
    }
}

# Disable P3 bootstrap selection on the next app launch. Preserve the full
# artifact/manifest/probe directory for diagnosis and lineage.
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteRequest)

$summaryPath = Join-Path $ProbeWorkspace "p3-quest2-reference-probe-summary.json"
$summary = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-probe-summary"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    p3_quest2_device_handoff_sha256 = Sha256 $DeviceHandoffReceipt
    p3_runtime_manifest_sha256 = Sha256 $manifestPath
    p3_quest2_machine_probe_sha256 = Sha256 $probePath
    observed_refresh_hz = [double]$probe.observed_refresh_hz
    p95_frame_time_ms = [double]$probe.p95_frame_time_ms
    installed_student_hashes_verified_on_device = $true
    xr_management_version = $xrManagementVersion
    openxr_version = $openXrVersion
    target_refresh_hz = $targetRefreshHz
    max_frame_time_ms = $maxFrameTimeMs
    runtime_loaded = $true
    stereo_rendering_observed = $true
    vr_safe_frame_pacing_observed = $true
    stereo_rendering_mode = [string]$probe.stereo_rendering_mode
    eye_texture_width = [int]$probe.eye_texture_width
    eye_texture_height = [int]$probe.eye_texture_height
    human_runtime_visual_acceptance_required = $true
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Quest2 P3 reference machine probe: COMPLETE"
Write-Host "Installed hashes verified: TRUE"
Write-Host "VRM/Humanoid load:         TRUE"
Write-Host "Observed refresh:          $($probe.observed_refresh_hz) Hz"
Write-Host "P95 frame time:            $($probe.p95_frame_time_ms) ms"
Write-Host "OpenXR loader/device:      TRUE"
Write-Host "Stereo rendering:          TRUE / $($probe.stereo_rendering_mode)"
Write-Host "VR-safe frame pacing:      TRUE"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Photoreal acceptance:      FALSE"
Write-Host "Production:                FALSE"
Write-Host "Probe:                     $probePath"
Write-Host "Summary:                   $summaryPath"
exit 0
 -or $openXrVersion -notmatch '^\d+\.\d+\.\d+ = [string]$contract.unity_editor_version
$pinnedAdb = Need-File -Path (Join-Path "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe") -Label "Pinned Unity Android adb"
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requestedAdb = Need-File -Path $AdbExe -Label "Requested adb"
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [StringComparison]::OrdinalIgnoreCase)) {
        throw "P3 Quest2 reference probe refuses non-pinned adb: $requestedAdb"
    }
}
$script:AdbExe = $pinnedAdb
$script:Serial = $Serial

if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(
        Invoke-Adb -Arguments @("devices") -Capture |
            Select-Object -Skip 1 |
            Where-Object { $_ -match '^\S+\s+device$' }
    )
    if ($devices.Count -ne 1) {
        throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached."
    }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(Quest\s*2|Oculus\s*Quest\s*2)') {
    throw "Connected adb device is not an exact Quest 2: '$model'"
}

if ([string]::IsNullOrWhiteSpace($ProbeWorkspace)) {
    $ProbeWorkspace = Join-Path $RuntimeReviewWorkspace "p3-quest2-reference-probe"
} else {
    $ProbeWorkspace = [IO.Path]::GetFullPath($ProbeWorkspace)
}
if (Test-Path -LiteralPath $ProbeWorkspace) {
    throw "P3 Quest2 reference probe workspace already exists: $ProbeWorkspace"
}
New-Item -ItemType Directory -Path $ProbeWorkspace | Out-Null
$ProbeWorkspace = Need-Directory -Path $ProbeWorkspace -Label "P3 Quest2 reference probe workspace"

$apk = Join-Path $repoRoot "reference-renderer\Builds\Quest\BodyRigReferenceProbe.apk"
$buildScript = Need-File -Path (Join-Path $repoRoot "reference-renderer\build-reference-renderer.ps1") -Label "Reference renderer build operator"
$buildArgs = @{
    Platform = "Quest"
    Output = $apk
}
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) {
    $buildArgs.UnityExe = $UnityExe
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 P3 REFERENCE PROBE"
Write-Host "Revision:                 $head"
Write-Host "Runtime review plan:      $planPath"
Write-Host "Device handoff:           $DeviceHandoffReceipt"
Write-Host "Quest device:             $model"
Write-Host "Artifacts:                $($normalizedArtifacts.Count)"
Write-Host "Renderer:                 canonical Unity/UniVRM reference project"
Write-Host "XR/OpenXR authority:      NOT PINNED"
Write-Host "Stereo acceptance:        BLOCKED / FALSE"
Write-Host "Production:               FALSE"
Write-Host "============================================================"

& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Reference renderer Quest build failed with exit code $LASTEXITCODE."
}
$apk = Need-File -Path $apk -Label "Reference renderer Quest APK"

$applicationId = [string]$contract.application_id
$remoteRoot = "/sdcard/Android/data/$applicationId/files/BodyRig/P3/current"
$remoteOutput = "$remoteRoot/output"
$remoteManifest = "$remoteRoot/p3-runtime-manifest.json"
$remoteRequest = "$remoteRoot/run-p3-probe.request"
$remoteProbe = "$remoteRoot/p3-quest2-machine-probe.json"

Invoke-Adb -Arguments @("install", "-r", $apk)
Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRoot' && mkdir -p '$remoteOutput'")

foreach ($artifact in $normalizedArtifacts) {
    $remotePath = "$remoteOutput/$([string]$artifact.relative_path)"
    $slash = $remotePath.LastIndexOf("/")
    $remoteParent = $remotePath.Substring(0, $slash)
    Invoke-Adb -Arguments @("shell", "mkdir", "-p", $remoteParent)
    Invoke-Adb -Arguments @("push", [string]$artifact.local_path, $remotePath)
}

$manifestPath = Join-Path $ProbeWorkspace "p3-runtime-manifest.json"
$manifestArtifacts = @(
    $normalizedArtifacts | ForEach-Object {
        [ordered]@{
            kind = [string]$_.kind
            relative_path = [string]$_.relative_path
            size_bytes = [int64]$_.size_bytes
            sha256 = [string]$_.sha256
        }
    }
)
$runtimeManifest = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-runtime"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    performer_id = [string]$plan.performer_id
    target_device_family = "meta-quest"
    target_device_model = "quest-2"
    avatar_relative_path = $avatarRelative
    student_artifacts = $manifestArtifacts
}
$runtimeManifest | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Invoke-Adb -Arguments @("push", $manifestPath, $remoteManifest)
Invoke-Adb -Arguments @("shell", "touch", $remoteRequest)
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteProbe)
Invoke-Adb -Arguments @("shell", "monkey", "-p", $applicationId, "1")

$ready = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Seconds 1
    $state = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ]; then echo ready; fi") -Capture) -join "").Trim()
    if ($state -eq "ready") {
        $ready = $true
        break
    }
}
if (-not $ready) {
    throw "Quest 2 reference renderer did not produce P3 machine evidence. Inspect headset and adb logcat; request marker was preserved."
}

$probePath = Join-Path $ProbeWorkspace "p3-quest2-machine-probe.json"
Invoke-Adb -Arguments @("pull", $remoteProbe, $probePath)
$probePath = Need-File -Path $probePath -Label "P3 Quest2 machine probe"
$probe = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if (
    [string]$probe.format -ne "bodyrig-photoreal-p3-quest2-machine-probe" -or
    $probe.version -is [bool] -or
    [double]$probe.version -ne 1.0 -or
    [string]$probe.bodyrig_revision -ne $head -or
    (Need-Sha256 -Value ([string]$probe.p3_device_runtime_review_plan_sha256) -Label "probe plan SHA-256") -ne $planSha -or
    [string]$probe.target_device_family -ne "meta-quest" -or
    [string]$probe.target_device_model -ne "quest-2"
) {
    throw "Quest2 P3 machine probe lineage/format mismatch."
}

foreach ($field in @(
    "installed_student_hashes_verified_on_device",
    "vrm10_loaded",
    "humanoid_valid",
    "required_bones_valid",
    "runtime_loaded",
    "human_runtime_visual_acceptance_required"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $true) {
        throw "Quest2 P3 machine probe requirement missing: $field"
    }
}
foreach ($field in @(
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $false) {
        throw "Quest2 P3 machine probe crossed its v1 authority boundary: $field"
    }
}
if ([string]$probe.stereo_authority -ne "blocked-until-canonical-xr-runtime-is-pinned") {
    throw "Quest2 P3 machine probe stereo authority is not fail-closed."
}
if ([double]$probe.observed_refresh_hz -le 0 -or [double]$probe.p95_frame_time_ms -le 0 -or [int]$probe.frame_time_sample_count -lt 120) {
    throw "Quest2 P3 machine probe performance measurements are invalid."
}

$installedMap = @{}
foreach ($item in @($probe.installed_student_artifacts)) {
    $installedMap[([string]$item.relative_path).Replace("\", "/")] = Need-Sha256 -Value ([string]$item.sha256) -Label "installed artifact SHA-256"
}
if ($installedMap.Count -ne $normalizedArtifacts.Count) {
    throw "Quest2 P3 machine probe installed artifact universe is incomplete."
}
foreach ($artifact in $normalizedArtifacts) {
    $relative = [string]$artifact.relative_path
    if (-not $installedMap.ContainsKey($relative) -or $installedMap[$relative] -ne [string]$artifact.sha256) {
        throw "Quest2 P3 machine probe installed bytes differ from P3 plan: $relative"
    }
}

# Disable P3 bootstrap selection on the next app launch. Preserve the full
# artifact/manifest/probe directory for diagnosis and lineage.
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteRequest)

$summaryPath = Join-Path $ProbeWorkspace "p3-quest2-reference-probe-summary.json"
$summary = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-probe-summary"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    p3_quest2_device_handoff_sha256 = Sha256 $DeviceHandoffReceipt
    p3_runtime_manifest_sha256 = Sha256 $manifestPath
    p3_quest2_machine_probe_sha256 = Sha256 $probePath
    observed_refresh_hz = [double]$probe.observed_refresh_hz
    p95_frame_time_ms = [double]$probe.p95_frame_time_ms
    installed_student_hashes_verified_on_device = $true
    runtime_loaded = $true
    stereo_rendering_observed = $false
    vr_safe_frame_pacing_observed = $false
    xr_runtime_blocker = "canonical-openxr-runtime-not-pinned"
    human_runtime_visual_acceptance_required = $true
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Quest2 P3 reference machine probe: COMPLETE"
Write-Host "Installed hashes verified: TRUE"
Write-Host "VRM/Humanoid load:         TRUE"
Write-Host "Observed refresh:          $($probe.observed_refresh_hz) Hz"
Write-Host "P95 frame time:            $($probe.p95_frame_time_ms) ms"
Write-Host "Stereo rendering:          FALSE / BLOCKED ON XR PIN"
Write-Host "VR-safe frame pacing:      FALSE / BLOCKED ON XR PIN"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Photoreal acceptance:      FALSE"
Write-Host "Production:                FALSE"
Write-Host "Probe:                     $probePath"
Write-Host "Summary:                   $summaryPath"
exit 0
) {
    throw "Quest XR package version pins are invalid."
}
$packageManifestPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\Packages\manifest.json") -Label "Reference renderer package manifest"
$packageManifest = Get-Content -LiteralPath $packageManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    [string]$packageManifest.dependencies."com.unity.xr.management" -ne $xrManagementVersion -or
    [string]$packageManifest.dependencies."com.unity.xr.openxr" -ne $openXrVersion
) {
    throw "Reference renderer package manifest differs from the canonical Quest XR pins."
}

$targetRefreshHz = [double]$plan.target_profile.target_refresh_hz
$maxFrameTimeMs = [double]$plan.target_profile.max_frame_time_ms
if (
    [double]::IsNaN($targetRefreshHz) -or [double]::IsInfinity($targetRefreshHz) -or $targetRefreshHz -le 0 -or
    [double]::IsNaN($maxFrameTimeMs) -or [double]::IsInfinity($maxFrameTimeMs) -or $maxFrameTimeMs -le 0 -or
    $plan.target_profile.stereo_rendering_required -isnot [bool] -or
    $plan.target_profile.stereo_rendering_required -ne $true -or
    $plan.target_profile.vr_safe_frame_pacing_required -isnot [bool] -or
    $plan.target_profile.vr_safe_frame_pacing_required -ne $true
) {
    throw "P3 runtime review plan has invalid Quest XR performance requirements."
}

$unityVersion = [string]$contract.unity_editor_version
$pinnedAdb = Need-File -Path (Join-Path "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe") -Label "Pinned Unity Android adb"
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requestedAdb = Need-File -Path $AdbExe -Label "Requested adb"
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [StringComparison]::OrdinalIgnoreCase)) {
        throw "P3 Quest2 reference probe refuses non-pinned adb: $requestedAdb"
    }
}
$script:AdbExe = $pinnedAdb
$script:Serial = $Serial

if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(
        Invoke-Adb -Arguments @("devices") -Capture |
            Select-Object -Skip 1 |
            Where-Object { $_ -match '^\S+\s+device$' }
    )
    if ($devices.Count -ne 1) {
        throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached."
    }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(Quest\s*2|Oculus\s*Quest\s*2)') {
    throw "Connected adb device is not an exact Quest 2: '$model'"
}

if ([string]::IsNullOrWhiteSpace($ProbeWorkspace)) {
    $ProbeWorkspace = Join-Path $RuntimeReviewWorkspace "p3-quest2-reference-probe"
} else {
    $ProbeWorkspace = [IO.Path]::GetFullPath($ProbeWorkspace)
}
if (Test-Path -LiteralPath $ProbeWorkspace) {
    throw "P3 Quest2 reference probe workspace already exists: $ProbeWorkspace"
}
New-Item -ItemType Directory -Path $ProbeWorkspace | Out-Null
$ProbeWorkspace = Need-Directory -Path $ProbeWorkspace -Label "P3 Quest2 reference probe workspace"

$apk = Join-Path $repoRoot "reference-renderer\Builds\Quest\BodyRigReferenceProbe.apk"
$buildScript = Need-File -Path (Join-Path $repoRoot "reference-renderer\build-reference-renderer.ps1") -Label "Reference renderer build operator"
$buildArgs = @{
    Platform = "Quest"
    Output = $apk
}
if (-not [string]::IsNullOrWhiteSpace($UnityExe)) {
    $buildArgs.UnityExe = $UnityExe
}

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - QUEST2 P3 REFERENCE PROBE"
Write-Host "Revision:                 $head"
Write-Host "Runtime review plan:      $planPath"
Write-Host "Device handoff:           $DeviceHandoffReceipt"
Write-Host "Quest device:             $model"
Write-Host "Artifacts:                $($normalizedArtifacts.Count)"
Write-Host "Renderer:                 canonical Unity/UniVRM reference project"
Write-Host "XR/OpenXR authority:      NOT PINNED"
Write-Host "Stereo acceptance:        BLOCKED / FALSE"
Write-Host "Production:               FALSE"
Write-Host "============================================================"

& $buildScript @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Reference renderer Quest build failed with exit code $LASTEXITCODE."
}
$apk = Need-File -Path $apk -Label "Reference renderer Quest APK"

$applicationId = [string]$contract.application_id
$remoteRoot = "/sdcard/Android/data/$applicationId/files/BodyRig/P3/current"
$remoteOutput = "$remoteRoot/output"
$remoteManifest = "$remoteRoot/p3-runtime-manifest.json"
$remoteRequest = "$remoteRoot/run-p3-probe.request"
$remoteProbe = "$remoteRoot/p3-quest2-machine-probe.json"

Invoke-Adb -Arguments @("install", "-r", $apk)
Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRoot' && mkdir -p '$remoteOutput'")

foreach ($artifact in $normalizedArtifacts) {
    $remotePath = "$remoteOutput/$([string]$artifact.relative_path)"
    $slash = $remotePath.LastIndexOf("/")
    $remoteParent = $remotePath.Substring(0, $slash)
    Invoke-Adb -Arguments @("shell", "mkdir", "-p", $remoteParent)
    Invoke-Adb -Arguments @("push", [string]$artifact.local_path, $remotePath)
}

$manifestPath = Join-Path $ProbeWorkspace "p3-runtime-manifest.json"
$manifestArtifacts = @(
    $normalizedArtifacts | ForEach-Object {
        [ordered]@{
            kind = [string]$_.kind
            relative_path = [string]$_.relative_path
            size_bytes = [int64]$_.size_bytes
            sha256 = [string]$_.sha256
        }
    }
)
$runtimeManifest = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-runtime"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    performer_id = [string]$plan.performer_id
    target_device_family = "meta-quest"
    target_device_model = "quest-2"
    avatar_relative_path = $avatarRelative
    student_artifacts = $manifestArtifacts
}
$runtimeManifest | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Invoke-Adb -Arguments @("push", $manifestPath, $remoteManifest)
Invoke-Adb -Arguments @("shell", "touch", $remoteRequest)
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteProbe)
Invoke-Adb -Arguments @("shell", "monkey", "-p", $applicationId, "1")

$ready = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Seconds 1
    $state = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ]; then echo ready; fi") -Capture) -join "").Trim()
    if ($state -eq "ready") {
        $ready = $true
        break
    }
}
if (-not $ready) {
    throw "Quest 2 reference renderer did not produce P3 machine evidence. Inspect headset and adb logcat; request marker was preserved."
}

$probePath = Join-Path $ProbeWorkspace "p3-quest2-machine-probe.json"
Invoke-Adb -Arguments @("pull", $remoteProbe, $probePath)
$probePath = Need-File -Path $probePath -Label "P3 Quest2 machine probe"
$probe = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

if (
    [string]$probe.format -ne "bodyrig-photoreal-p3-quest2-machine-probe" -or
    $probe.version -is [bool] -or
    [double]$probe.version -ne 1.0 -or
    [string]$probe.bodyrig_revision -ne $head -or
    (Need-Sha256 -Value ([string]$probe.p3_device_runtime_review_plan_sha256) -Label "probe plan SHA-256") -ne $planSha -or
    [string]$probe.target_device_family -ne "meta-quest" -or
    [string]$probe.target_device_model -ne "quest-2"
) {
    throw "Quest2 P3 machine probe lineage/format mismatch."
}

foreach ($field in @(
    "installed_student_hashes_verified_on_device",
    "vrm10_loaded",
    "humanoid_valid",
    "required_bones_valid",
    "runtime_loaded",
    "human_runtime_visual_acceptance_required"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $true) {
        throw "Quest2 P3 machine probe requirement missing: $field"
    }
}
foreach ($field in @(
    "stereo_rendering_observed",
    "vr_safe_frame_pacing_observed",
    "runtime_acceptance_authority",
    "photoreal_acceptance_authority",
    "production_activation"
)) {
    if ($probe.$field -isnot [bool] -or $probe.$field -ne $false) {
        throw "Quest2 P3 machine probe crossed its v1 authority boundary: $field"
    }
}
if ([string]$probe.stereo_authority -ne "blocked-until-canonical-xr-runtime-is-pinned") {
    throw "Quest2 P3 machine probe stereo authority is not fail-closed."
}
if ([double]$probe.observed_refresh_hz -le 0 -or [double]$probe.p95_frame_time_ms -le 0 -or [int]$probe.frame_time_sample_count -lt 120) {
    throw "Quest2 P3 machine probe performance measurements are invalid."
}

$installedMap = @{}
foreach ($item in @($probe.installed_student_artifacts)) {
    $installedMap[([string]$item.relative_path).Replace("\", "/")] = Need-Sha256 -Value ([string]$item.sha256) -Label "installed artifact SHA-256"
}
if ($installedMap.Count -ne $normalizedArtifacts.Count) {
    throw "Quest2 P3 machine probe installed artifact universe is incomplete."
}
foreach ($artifact in $normalizedArtifacts) {
    $relative = [string]$artifact.relative_path
    if (-not $installedMap.ContainsKey($relative) -or $installedMap[$relative] -ne [string]$artifact.sha256) {
        throw "Quest2 P3 machine probe installed bytes differ from P3 plan: $relative"
    }
}

# Disable P3 bootstrap selection on the next app launch. Preserve the full
# artifact/manifest/probe directory for diagnosis and lineage.
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteRequest)

$summaryPath = Join-Path $ProbeWorkspace "p3-quest2-reference-probe-summary.json"
$summary = [ordered]@{
    format = "bodyrig-photoreal-p3-quest2-reference-probe-summary"
    version = 1
    bodyrig_revision = $head
    p3_device_runtime_review_plan_sha256 = $planSha
    p3_quest2_device_handoff_sha256 = Sha256 $DeviceHandoffReceipt
    p3_runtime_manifest_sha256 = Sha256 $manifestPath
    p3_quest2_machine_probe_sha256 = Sha256 $probePath
    observed_refresh_hz = [double]$probe.observed_refresh_hz
    p95_frame_time_ms = [double]$probe.p95_frame_time_ms
    installed_student_hashes_verified_on_device = $true
    runtime_loaded = $true
    stereo_rendering_observed = $false
    vr_safe_frame_pacing_observed = $false
    xr_runtime_blocker = "canonical-openxr-runtime-not-pinned"
    human_runtime_visual_acceptance_required = $true
    runtime_acceptance_authority = $false
    photoreal_acceptance_authority = $false
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Quest2 P3 reference machine probe: COMPLETE"
Write-Host "Installed hashes verified: TRUE"
Write-Host "VRM/Humanoid load:         TRUE"
Write-Host "Observed refresh:          $($probe.observed_refresh_hz) Hz"
Write-Host "P95 frame time:            $($probe.p95_frame_time_ms) ms"
Write-Host "Stereo rendering:          FALSE / BLOCKED ON XR PIN"
Write-Host "VR-safe frame pacing:      FALSE / BLOCKED ON XR PIN"
Write-Host "Runtime acceptance:        FALSE"
Write-Host "Photoreal acceptance:      FALSE"
Write-Host "Production:                FALSE"
Write-Host "Probe:                     $probePath"
Write-Host "Summary:                   $summaryPath"
exit 0
