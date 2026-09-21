param(
    [Parameter(Mandatory = $true)][string]$ReviewRuntimeWorkspace,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$EvidenceDir = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "P3 Quest review probe is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the P3 Quest review probe."
}

$ApplicationId = "dk.ternedal.bodyrig.p3review"

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $clean = $Value.Trim().ToLowerInvariant()
    if ($clean -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $clean
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value,[Parameter(Mandatory = $true)][string]$Label)
    $clean = $Value.Trim().ToLowerInvariant()
    if ($clean -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $clean
}

function Test-V1Version($Value) {
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    return [decimal]$Value -eq [decimal]1
}

function Invoke-Adb {
    param([Parameter(Mandatory = $true)][object[]]$Arguments,[switch]$Capture)
    $all = @()
    if (-not [string]::IsNullOrWhiteSpace($script:Serial)) { $all += @("-s", $script:Serial) }
    $all += $Arguments
    if ($Capture) {
        $lines = @(& $script:AdbExe @all 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "adb failed: $($lines -join [Environment]::NewLine)" }
        return $lines
    }
    & $script:AdbExe @all
    if ($LASTEXITCODE -ne 0) { throw "adb failed with exit code $($LASTEXITCODE): $($Arguments -join ' ')" }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$ReviewRuntimeWorkspace = Need-Directory -Path $ReviewRuntimeWorkspace -Label "P3 Quest review-runtime workspace"
$manifestPath = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "p3-quest2-review-manifest.json") -Label "P3 Quest review manifest"
$receiptPath = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "p3-quest2-review-runtime-receipt.json") -Label "P3 Quest review-runtime receipt"
$avatarPath = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "avatar.vrm") -Label "P3 Quest review avatar"
$basecolorPath = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "basecolor.png") -Label "P3 Quest review basecolor"
$provenancePath = Need-File -Path (Join-Path $ReviewRuntimeWorkspace "quest2-modular-provenance.json") -Label "P3 Quest review provenance"

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = Need-Revision ([string]$headRaw[0]) "BodyRig HEAD"
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "P3 Quest review probe requires an exact clean BodyRig checkout." }

try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
} catch { throw "P3 Quest review runtime JSON is unreadable." }

if (
    [string]$manifest.format -ne "bodyrig-photoreal-p3-quest2-review-runtime-manifest" -or
    -not (Test-V1Version $manifest.version) -or
    (Need-Revision ([string]$manifest.bodyrig_revision) "review manifest BodyRig revision") -ne $head -or
    [string]$manifest.target_device_family -ne "meta-quest" -or
    [string]$manifest.target_device_model -ne "quest-2" -or
    [string]$manifest.student_representation -ne "skinned-mesh-pbr" -or
    $manifest.physical_review_only -ne $true -or
    $manifest.comparison_only -ne $true -or
    $manifest.physical_device_evidence_present -ne $false -or
    $manifest.runtime_acceptance_authority -ne $false -or
    $manifest.photoreal_acceptance_authority -ne $false -or
    $manifest.production_activation -ne $false
) { throw "P3 Quest review manifest is not a valid review-only authority." }

if (
    [string]$receipt.format -ne "bodyrig-photoreal-p3-quest2-review-runtime-workspace" -or
    -not (Test-V1Version $receipt.version) -or
    $receipt.artifact_bytes_verified_by_core -ne $true -or
    $receipt.physical_review_only -ne $true -or
    $receipt.comparison_only -ne $true -or
    $receipt.runtime_acceptance_authority -ne $false -or
    $receipt.photoreal_acceptance_authority -ne $false -or
    $receipt.production_activation -ne $false
) { throw "P3 Quest review-runtime receipt is not valid." }

$manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$avatarSha = (Get-FileHash -LiteralPath $avatarPath -Algorithm SHA256).Hash.ToLowerInvariant()
$basecolorSha = (Get-FileHash -LiteralPath $basecolorPath -Algorithm SHA256).Hash.ToLowerInvariant()
$provenanceSha = (Get-FileHash -LiteralPath $provenancePath -Algorithm SHA256).Hash.ToLowerInvariant()
if (
    $avatarSha -ne (Need-Sha256 ([string]$manifest.avatar_sha256) "manifest.avatar_sha256") -or
    $basecolorSha -ne (Need-Sha256 ([string]$manifest.basecolor_sha256) "manifest.basecolor_sha256") -or
    $provenanceSha -ne (Need-Sha256 ([string]$manifest.provenance_sha256) "manifest.provenance_sha256") -or
    $manifestSha -ne (Need-Sha256 ([string]$receipt.review_manifest_sha256) "receipt.review_manifest_sha256")
) { throw "P3 Quest review-runtime bytes drifted before physical probe." }

$contractPath = Need-File -Path (Join-Path $repoRoot "reference-renderer\renderer-contract.json") -Label "Reference renderer contract"
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is invalid JSON." }
if (
    [string]$contract.format -ne "bodyrig-reference-renderer-contract" -or
    -not (Test-V1Version $contract.version) -or
    [string]$contract.unity_editor_version -notmatch '^6000\.3\.\d+f\d+$'
) { throw "Reference renderer contract is invalid for P3 review." }

$pinnedAdb = Join-Path "C:\Program Files\Unity\Hub\Editor\$([string]$contract.unity_editor_version)\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe"
$pinnedAdb = Need-File -Path $pinnedAdb -Label "Pinned Unity Android adb"
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requested = Need-File -Path $AdbExe -Label "Requested adb"
    if (-not [string]::Equals($requested, $pinnedAdb, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "P3 Quest review requires the pinned Unity Android adb.exe."
    }
}

if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
    $EvidenceDir = Join-Path (Split-Path -Parent $ReviewRuntimeWorkspace) "quest2-review-evidence"
} else {
    $EvidenceDir = [System.IO.Path]::GetFullPath($EvidenceDir)
}
if (Test-Path -LiteralPath $EvidenceDir) { throw "P3 Quest review evidence directory already exists: $EvidenceDir" }
$evidenceParent = Split-Path -Parent $EvidenceDir
if (-not (Test-Path -LiteralPath $evidenceParent -PathType Container)) { throw "P3 Quest review evidence parent does not exist: $evidenceParent" }

$attemptDir = Join-Path $evidenceParent (".bodyrig-p3-quest-review-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attemptDir | Out-Null
$stagedProbe = Join-Path $attemptDir "p3-quest2-review-render-probe.json"
$committed = $false

try {
    $script:AdbExe = $pinnedAdb
    $script:Serial = $Serial

    if ([string]::IsNullOrWhiteSpace($script:Serial)) {
        $devices = @(Invoke-Adb -Arguments @("devices") -Capture | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
        if ($devices.Count -ne 1) { throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when needed." }
        $script:Serial = ($devices[0] -split '\s+')[0]
    }

    $model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
    if ($model -notmatch '(?i)quest|oculus') { throw "Connected adb device is not Quest/Oculus-class: '$model'" }

    $rendererRoot = Join-Path $repoRoot "reference-renderer"
    $buildScript = Need-File -Path (Join-Path $rendererRoot "build-reference-renderer.ps1") -Label "Reference renderer build operator"
    $apk = Join-Path $rendererRoot "Builds\Quest\BodyRigP3QuestReview.apk"
    if (-not $SkipBuild) {
        $buildDir = Split-Path -Parent $apk
        if (Test-Path -LiteralPath $buildDir) { Remove-Item -LiteralPath $buildDir -Recurse -Force }
        $buildArgs = @{ Platform = "P3QuestReview"; Output = $apk }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "P3 Quest review APK build failed with exit code $LASTEXITCODE." }
    }
    $apk = Need-File -Path $apk -Label "P3 Quest review APK"

    $remoteRoot = "/sdcard/Android/data/$ApplicationId/files/BodyRig/p3-review"
    $remoteProbe = "$remoteRoot/p3-quest2-review-render-probe.json"

    Write-Host "============================================================"
    Write-Host "BODYRIG P3 QUEST REVIEW RENDERABILITY PROBE"
    Write-Host "Revision:          $head"
    Write-Host "Device:            $($script:Serial) | $model"
    Write-Host "ADB authority:     $pinnedAdb"
    Write-Host "Review manifest:   $manifestPath"
    Write-Host "Review APK:        $apk"
    Write-Host "Application id:    $ApplicationId"
    Write-Host "XR runtime:        NOT PRESENT / NOT CLAIMED"
    Write-Host "Stereo acceptance: FALSE"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    Invoke-Adb -Arguments @("install", "-r", $apk)
    Invoke-Adb -Arguments @("shell", "am", "force-stop", $ApplicationId)
    Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRoot' && mkdir -p '$remoteRoot'")
    foreach ($source in @($manifestPath, $avatarPath, $basecolorPath, $provenancePath)) {
        Invoke-Adb -Arguments @("push", $source, "$remoteRoot/")
    }
    Invoke-Adb -Arguments @("shell", "monkey", "-p", $ApplicationId, "1")

    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        Start-Sleep -Seconds 1
        $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ]; then echo ready; fi") -Capture) -join "").Trim()
        if ($check -eq "ready") { $ready = $true; break }
    }
    if (-not $ready) { throw "P3 Quest review app did not produce renderability evidence. Inspect headset/logcat; no local evidence was committed." }

    Invoke-Adb -Arguments @("pull", $remoteProbe, $stagedProbe)
    $stagedProbe = Need-File -Path $stagedProbe -Label "Pulled P3 Quest review probe"
    try { $probe = Get-Content -LiteralPath $stagedProbe -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100 }
    catch { throw "P3 Quest review probe is invalid JSON." }

    if (
        [string]$probe.format -ne "bodyrig-photoreal-p3-quest2-review-render-probe" -or
        -not (Test-V1Version $probe.version) -or
        (Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $head -or
        [string]$probe.unity_platform -ne "Android" -or
        [string]$probe.device_model -notmatch '(?i)quest|oculus' -or
        [string]$probe.performer_id -ne [string]$manifest.performer_id -or
        (Need-Sha256 ([string]$probe.p3_device_runtime_review_plan_sha256) "probe runtime plan") -ne (Need-Sha256 ([string]$manifest.p3_device_runtime_review_plan_sha256) "manifest runtime plan") -or
        (Need-Sha256 ([string]$probe.review_manifest_sha256) "probe review manifest") -ne $manifestSha -or
        (Need-Sha256 ([string]$probe.avatar_sha256) "probe avatar") -ne $avatarSha -or
        (Need-Sha256 ([string]$probe.basecolor_sha256) "probe basecolor") -ne $basecolorSha -or
        (Need-Sha256 ([string]$probe.provenance_sha256) "probe provenance") -ne $provenanceSha
    ) { throw "P3 Quest review probe does not bind the exact review runtime/device." }

    foreach ($field in @(
        "vrm10_loaded","humanoid_valid","required_bones_valid",
        "specialized_eye_component_instantiated","specialized_eye_component_visible",
        "teacher_hair_component_instantiated","teacher_hair_component_visible",
        "physical_device_observed","physical_review_only","comparison_only"
    )) {
        if ($probe.$field -isnot [bool] -or $probe.$field -ne $true) { throw "P3 Quest review renderability requirement missing: $field" }
    }
    foreach ($field in @(
        "xr_runtime_present","stereo_rendering_observed","vr_safe_frame_pacing_observed",
        "physical_runtime_review_complete","runtime_acceptance_authority",
        "photoreal_acceptance_authority","production_activation"
    )) {
        if ($probe.$field -isnot [bool] -or $probe.$field -ne $false) { throw "P3 Quest review probe crossed its diagnostic boundary: $field" }
    }

    Move-Item -LiteralPath $attemptDir -Destination $EvidenceDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container)) {
        Remove-Item -LiteralPath $attemptDir -Recurse -Force
    }
}

$finalProbe = Need-File -Path (Join-Path $EvidenceDir "p3-quest2-review-render-probe.json") -Label "Committed P3 Quest review probe"
Write-Host ""
Write-Host "P3 Quest renderability: PASS"
Write-Host "Physical Quest:         OBSERVED"
Write-Host "VRM/Humanoid:           LOADED"
Write-Host "Eye component:          VISIBLE"
Write-Host "Hair component:         VISIBLE"
Write-Host "XR runtime:             FALSE"
Write-Host "Stereo acceptance:      FALSE"
Write-Host "Photoreal acceptance:   FALSE"
Write-Host "Production:             FALSE"
Write-Host "Evidence:               $finalProbe"
Write-Host "The review app remains open for visual inspection."
exit 0
