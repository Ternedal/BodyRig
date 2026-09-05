param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$ProbeOutput = "",
    [string]$DeformationOutput = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig physical evidence path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical evidence path."
}
$pwshAuthority = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshAuthority) {
    throw "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical evidence path."
}

$ApplicationId = "dk.ternedal.bodyrig.reference"
$RendererName = "BodyRig Reference Renderer"
$RendererVersion = "reference-v1/univrm-0.131.2"

function Invoke-Adb {
    param([Parameter(Mandatory = $true)][object[]]$Arguments, [switch]$Capture)
    $all = @()
    if (-not [string]::IsNullOrWhiteSpace($script:Serial)) { $all += @("-s", $script:Serial) }
    $all += $Arguments
    if ($Capture) {
        $lines = @(& $script:AdbExe @all 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "adb failed: $($lines -join [Environment]::NewLine)" }
        return $lines
    }
    & $script:AdbExe @all
    if ($LASTEXITCODE -ne 0) { throw "adb failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')" }
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
    return $normalized
}
function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $normalized
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }

$contractPath = Join-Path $repoRoot "reference-renderer\renderer-contract.json"
if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) { throw "Reference renderer contract not found: $contractPath" }
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is not valid JSON: $contractPath" }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
if ([string]$contract.unity_editor_version -notmatch '^6000\.3\.\d+f\d+$') { throw "Reference renderer contract contains an unsupported Unity editor version." }
if ([string]$contract.application_id -ne $ApplicationId) { throw "Reference renderer contract has an unsupported Quest application id." }
if ([string]$contract.renderer_name -ne $RendererName -or [string]$contract.renderer_version -ne $RendererVersion) { throw "Quest renderer identity does not match reference-renderer/renderer-contract.json." }
if ([string]$contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1") { throw "Reference renderer contract has an unsupported deformation sequence." }

$pinnedAdb = Join-Path "C:\Program Files\Unity\Hub\Editor\$([string]$contract.unity_editor_version)\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe"
if (-not (Test-Path -LiteralPath $pinnedAdb -PathType Leaf)) { throw "Pinned Unity Android adb not found: $pinnedAdb" }
$pinnedAdb = (Resolve-Path -LiteralPath $pinnedAdb).Path
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    if (-not (Test-Path -LiteralPath $AdbExe -PathType Leaf)) { throw "Requested adb executable not found: $AdbExe" }
    $requestedAdb = (Resolve-Path -LiteralPath $AdbExe).Path
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Quest physical renderer evidence requires the pinned Unity Android SDK adb.exe; refusing alternate adb: $requestedAdb"
    }
}
$pinnedAdb = [System.IO.Path]::GetFullPath($pinnedAdb)

$acceptancePath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$runtimeDir = Join-Path $AcceptanceDir "runtime"
$runtimeManifest = Join-Path $runtimeDir "runtime-manifest.json"
foreach ($required in @($acceptancePath, $runtimeManifest)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required Gate A artifact missing: $required" }
}
try { $acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json } catch { throw "Gate A acceptance report is not valid JSON: $acceptancePath" }
if ([string]$acceptance.format -ne "bodyrig-rig-acceptance" -or [int]$acceptance.version -ne 1 -or $acceptance.automated_pass -ne $true -or $acceptance.production_activation -ne $false) { throw "Gate A acceptance is not a valid non-activating automated PASS." }
$acceptedRevision = Need-Revision ([string]$acceptance.bodyrig_revision) "acceptance.bodyrig_revision"
$currentHeadLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$currentHead = Need-Revision ([string]$currentHeadLines[0].Trim()) "current BodyRig HEAD"
if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout does not match Gate A revision; refusing Quest physical renderer evidence." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; Quest physical renderer evidence requires the exact clean Gate A revision." }

$expectedRuntimeHash = Need-Sha256 ([string]$acceptance.runtime.manifest_sha256) "acceptance.runtime.manifest_sha256"
$actualRuntimeHash = (Get-FileHash -LiteralPath $runtimeManifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRuntimeHash -ne $expectedRuntimeHash) { throw "Runtime manifest bytes no longer match Gate A acceptance." }

$customProbe = -not [string]::IsNullOrWhiteSpace($ProbeOutput)
$customDeformation = -not [string]::IsNullOrWhiteSpace($DeformationOutput)
if ($customProbe -ne $customDeformation) { throw "Pass both -ProbeOutput and -DeformationOutput together, or neither." }
if (-not $customProbe) {
    $evidenceDir = Join-Path $AcceptanceDir "quest-evidence"
    $ProbeOutput = Join-Path $evidenceDir "quest-probe.json"
    $DeformationOutput = Join-Path $evidenceDir "quest-deformation-probe.json"
} else {
    $ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
    $DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
    $probeParent = Split-Path -Parent $ProbeOutput
    $deformationParent = Split-Path -Parent $DeformationOutput
    if (-not [string]::Equals($probeParent, $deformationParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Custom Quest probe/deformation outputs must share one dedicated evidence directory."
    }
    $evidenceDir = $probeParent
}
$evidenceDir = [System.IO.Path]::GetFullPath($evidenceDir)
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
$DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
if ([string]::Equals($ProbeOutput, $DeformationOutput, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Quest probe and deformation outputs must be distinct files." }
if (Test-Path -LiteralPath $evidenceDir) { throw "Quest canonical evidence directory already exists; refusing cross-attempt reuse: $evidenceDir" }
$evidenceParent = Split-Path -Parent $evidenceDir
if (-not (Test-Path -LiteralPath $evidenceParent -PathType Container)) { throw "Quest evidence parent directory not found: $evidenceParent" }

$attemptDir = Join-Path $evidenceParent (".bodyrig-quest-attempt-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attemptDir | Out-Null
$stagedProbe = Join-Path $attemptDir ([IO.Path]::GetFileName($ProbeOutput))
$stagedDeformation = Join-Path $attemptDir ([IO.Path]::GetFileName($DeformationOutput))
$committed = $false

try {
    $script:AdbExe = $pinnedAdb
    $script:Serial = $Serial

    if ([string]::IsNullOrWhiteSpace($Serial)) {
        $devices = @(Invoke-Adb -Arguments @("devices") -Capture | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
        if ($devices.Count -ne 1) { throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached." }
        $script:Serial = ($devices[0] -split '\s+')[0]
    }

    $model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
    if ($model -notmatch '(?i)quest|oculus') { throw "Connected adb device is not Quest/Oculus-class: '$model'" }

    $rendererRoot = Join-Path $repoRoot "reference-renderer"
    $buildScript = Join-Path $rendererRoot "build-reference-renderer.ps1"
    $apk = Join-Path $rendererRoot "Builds\Quest\BodyRigReferenceProbe.apk"
    if (-not $SkipBuild) {
        $buildDir = Split-Path -Parent $apk
        if (Test-Path -LiteralPath $buildDir) {
            Remove-Item -LiteralPath $buildDir -Recurse -Force
        }
        $buildArgs = @{ Platform = "Quest"; Output = $apk }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "BodyRig Quest reference renderer build failed with exit code $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw "Built Quest reference renderer APK not found: $apk" }

    $remoteRoot = "/sdcard/Android/data/$ApplicationId/files/BodyRig"
    $remoteRuntime = "$remoteRoot/runtime"
    $remoteProbe = "$remoteRoot/bodyrig-renderer-probe.json"
    $remoteDeformation = "$remoteRoot/bodyrig-deformation-probe.json"

    Write-Host "BodyRig Quest renderer Gate B physical probe"
    Write-Host "Revision:     $acceptedRevision"
    Write-Host "ADB authority: $($script:AdbExe)"
    Write-Host "ADB device:   $($script:Serial) | $model"
    Write-Host "Runtime:      $runtimeDir"
    Write-Host "Staging:      $attemptDir"
    Write-Host "Commit dir:   $evidenceDir"

    Invoke-Adb -Arguments @("install", "-r", $apk)
    Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRuntime' && mkdir -p '$remoteRuntime' && rm -f '$remoteProbe' '$remoteDeformation'")
    Invoke-Adb -Arguments @("push", (Join-Path $runtimeDir "."), "$remoteRuntime/")
    Invoke-Adb -Arguments @("shell", "monkey", "-p", $ApplicationId, "1")

    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        Start-Sleep -Seconds 1
        $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ] && [ -f '$remoteDeformation' ]; then echo ready; fi") -Capture) -join "").Trim()
        if ($check -eq "ready") { $ready = $true; break }
    }
    if (-not $ready) { throw "Quest player did not produce both machine and deformation evidence. Inspect the headset and adb logcat before retrying; local canonical evidence was not committed." }

    Invoke-Adb -Arguments @("pull", $remoteProbe, $stagedProbe)
    Invoke-Adb -Arguments @("pull", $remoteDeformation, $stagedDeformation)
    foreach ($required in @($stagedProbe, $stagedDeformation)) { if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "adb reported staged evidence pull success but local evidence is missing: $required" } }

    try { $probe = Get-Content -LiteralPath $stagedProbe -Raw | ConvertFrom-Json } catch { throw "Quest machine probe is not valid JSON: $stagedProbe" }
    if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "android-quest-class" -or [string]$probe.unity_platform -ne "Android") { throw "Quest machine probe has the wrong format/platform." }
    if ((Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $acceptedRevision) { throw "Quest player was not built from the exact Gate A BodyRig revision." }
    if ([string]$probe.device_model -notmatch '(?i)quest|oculus') { throw "Quest machine probe does not identify Quest/Oculus hardware." }
    if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Quest machine probe has no Unity build GUID." }
    if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) { throw "Quest machine probe renderer identity differs from the reference build contract." }
    if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) { throw "Quest machine probe does not identify the Gate A runtime manifest bytes." }

    try { $deformation = Get-Content -LiteralPath $stagedDeformation -Raw | ConvertFrom-Json } catch { throw "Quest deformation probe is not valid JSON: $stagedDeformation" }
    if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "android-quest-class" -or [string]$deformation.unity_platform -ne "Android") { throw "Quest deformation probe has the wrong format/platform." }
    if ((Need-Revision ([string]$deformation.bodyrig_revision) "deformation.bodyrig_revision") -ne $acceptedRevision -or [string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision) { throw "Quest deformation evidence was not produced by the same exact BodyRig revision as Gate A/machine probe." }
    if ([string]$deformation.device_model -notmatch '(?i)quest|oculus') { throw "Quest deformation probe does not identify Quest/Oculus hardware." }
    if ([string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) { throw "Quest deformation probe did not complete the fixed BodyRig pose sequence." }
    if ((Need-Sha256 ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $actualRuntimeHash -or [string]$deformation.body_id -ne [string]$probe.body_id -or [string]$deformation.package_sha256 -ne [string]$probe.package_sha256 -or [string]$deformation.avatar_sha256 -ne [string]$probe.avatar_sha256 -or [string]$deformation.bodyprint_sha256 -ne [string]$probe.bodyprint_sha256 -or [string]$deformation.build_guid -ne [string]$probe.build_guid) { throw "Quest deformation evidence is not byte/build-bound to the renderer machine probe." }
    $poseIds = @($deformation.poses | ForEach-Object { [string]$_.id })
    if (($poseIds -join ',') -ne 'neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion') { throw "Quest deformation probe pose sequence/order mismatch." }

    Move-Item -LiteralPath $attemptDir -Destination $evidenceDir
    $committed = $true
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container)) {
        Remove-Item -LiteralPath $attemptDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $ProbeOutput -PathType Leaf) -or -not (Test-Path -LiteralPath $DeformationOutput -PathType Leaf)) {
    throw "Quest evidence directory commit completed without both canonical files."
}
Write-Host "BodyRig Quest physical evidence: PASS | revision $acceptedRevision"
Write-Host "Evidence directory:   $evidenceDir"
Write-Host "Machine evidence:     $ProbeOutput"
Write-Host "Deformation evidence: $DeformationOutput"
Write-Host "The app remains on the headset cycling the same sequence for human visual inspection."
Write-Host "Human visual attestation is still required with record-reference-renderer-acceptance.ps1."
exit 0