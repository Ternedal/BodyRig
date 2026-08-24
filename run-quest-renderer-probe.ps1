param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "adb",
    [string]$Serial = "",
    [string]$ProbeOutput = "",
    [string]$DeformationOutput = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

$adbCommand = Get-Command $AdbExe -ErrorAction SilentlyContinue
if ($null -eq $adbCommand) { throw "adb not found: $AdbExe" }
$script:AdbExe = $adbCommand.Source
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
    $buildArgs = @{ Platform = "Quest"; Output = $apk }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
    & $buildScript @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "BodyRig Quest reference renderer build failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw "Built Quest reference renderer APK not found: $apk" }

if ([string]::IsNullOrWhiteSpace($ProbeOutput)) { $ProbeOutput = Join-Path $AcceptanceDir "quest-probe.json" }
if ([string]::IsNullOrWhiteSpace($DeformationOutput)) { $DeformationOutput = Join-Path $AcceptanceDir "quest-deformation-probe.json" }
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
$DeformationOutput = [System.IO.Path]::GetFullPath($DeformationOutput)
foreach ($output in @($ProbeOutput, $DeformationOutput)) { if (Test-Path -LiteralPath $output) { throw "Quest physical evidence already exists: $output" } }

$remoteRoot = "/sdcard/Android/data/$ApplicationId/files/BodyRig"
$remoteRuntime = "$remoteRoot/runtime"
$remoteProbe = "$remoteRoot/bodyrig-renderer-probe.json"
$remoteDeformation = "$remoteRoot/bodyrig-deformation-probe.json"

Write-Host "BodyRig Quest renderer Gate B physical probe"
Write-Host "Revision:     $acceptedRevision"
Write-Host "ADB device:   $($script:Serial) | $model"
Write-Host "Runtime:      $runtimeDir"
Write-Host "Machine:      $ProbeOutput"
Write-Host "Deformation:  $DeformationOutput"

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
if (-not $ready) { throw "Quest player did not produce both machine and deformation evidence. Inspect the headset and adb logcat before retrying; evidence was not fabricated." }

Invoke-Adb -Arguments @("pull", $remoteProbe, $ProbeOutput)
Invoke-Adb -Arguments @("pull", $remoteDeformation, $DeformationOutput)
foreach ($required in @($ProbeOutput, $DeformationOutput)) { if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "adb reported evidence pull success but local evidence is missing: $required" } }

try { $probe = Get-Content -LiteralPath $ProbeOutput -Raw | ConvertFrom-Json } catch { throw "Quest machine probe is not valid JSON: $ProbeOutput" }
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "android-quest-class" -or [string]$probe.unity_platform -ne "Android") { throw "Quest machine probe has the wrong format/platform." }
if ((Need-Revision ([string]$probe.bodyrig_revision) "probe.bodyrig_revision") -ne $acceptedRevision) { throw "Quest player was not built from the exact Gate A BodyRig revision." }
if ([string]$probe.device_model -notmatch '(?i)quest|oculus') { throw "Quest machine probe does not identify Quest/Oculus hardware." }
if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Quest machine probe has no Unity build GUID." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) { throw "Quest machine probe renderer identity differs from the reference build contract." }
if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) { throw "Quest machine probe does not identify the Gate A runtime manifest bytes." }

try { $deformation = Get-Content -LiteralPath $DeformationOutput -Raw | ConvertFrom-Json } catch { throw "Quest deformation probe is not valid JSON: $DeformationOutput" }
if ([string]$deformation.format -ne "bodyrig-deformation-probe" -or [int]$deformation.version -ne 1 -or [string]$deformation.platform -ne "android-quest-class" -or [string]$deformation.unity_platform -ne "Android") { throw "Quest deformation probe has the wrong format/platform." }
if ((Need-Revision ([string]$deformation.bodyrig_revision) "deformation.bodyrig_revision") -ne $acceptedRevision -or [string]$deformation.bodyrig_revision -ne [string]$probe.bodyrig_revision) { throw "Quest deformation evidence was not produced by the same exact BodyRig revision as Gate A/machine probe." }
if ([string]$deformation.device_model -notmatch '(?i)quest|oculus') { throw "Quest deformation probe does not identify Quest/Oculus hardware." }
if ([string]$deformation.sequence_revision -ne "humanoid-muscle-sweep-v1" -or [int]$deformation.pose_count -ne 6 -or $deformation.required_muscles_resolved -ne $true -or $deformation.restored_neutral -ne $true -or $deformation.complete -ne $true -or $deformation.manual_review_required -ne $true) { throw "Quest deformation probe did not complete the fixed BodyRig pose sequence." }
if ((Need-Sha256 ([string]$deformation.runtime_manifest_sha256) "deformation.runtime_manifest_sha256") -ne $actualRuntimeHash -or [string]$deformation.body_id -ne [string]$probe.body_id -or [string]$deformation.package_sha256 -ne [string]$probe.package_sha256 -or [string]$deformation.avatar_sha256 -ne [string]$probe.avatar_sha256 -or [string]$deformation.bodyprint_sha256 -ne [string]$probe.bodyprint_sha256 -or [string]$deformation.build_guid -ne [string]$probe.build_guid) { throw "Quest deformation evidence is not byte/build-bound to the renderer machine probe." }
$poseIds = @($deformation.poses | ForEach-Object { [string]$_.id })
if (($poseIds -join ',') -ne 'neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion') { throw "Quest deformation probe pose sequence/order mismatch." }

Write-Host "BodyRig Quest physical evidence: PASS | revision $acceptedRevision"
Write-Host "Machine evidence:     $ProbeOutput"
Write-Host "Deformation evidence: $DeformationOutput"
Write-Host "The app remains on the headset cycling the same sequence for human visual inspection."
Write-Host "Human visual attestation is still required with record-renderer-acceptance.ps1."
exit 0
