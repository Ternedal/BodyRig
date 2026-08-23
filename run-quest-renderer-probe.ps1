param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "adb",
    [string]$Serial = "",
    [string]$ProbeOutput = "",
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
    if ($LASTEXITCODE -ne 0) { throw "adb failed with exit code $LASTEXITCODE: $($Arguments -join ' ')" }
}

function Need-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{64}$') { throw "$Label is not a canonical SHA-256." }
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
if ([string]$acceptance.format -ne "bodyrig-rig-acceptance" -or [int]$acceptance.version -ne 1 -or $acceptance.automated_pass -ne $true -or $acceptance.production_activation -ne $false) {
    throw "Gate A acceptance is not a valid non-activating automated PASS."
}
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
$ProbeOutput = [System.IO.Path]::GetFullPath($ProbeOutput)
if (Test-Path -LiteralPath $ProbeOutput) { throw "Quest probe evidence already exists: $ProbeOutput" }

$remoteRoot = "/sdcard/Android/data/$ApplicationId/files/BodyRig"
$remoteRuntime = "$remoteRoot/runtime"
$remoteProbe = "$remoteRoot/bodyrig-renderer-probe.json"

Write-Host "BodyRig Quest renderer Gate B machine probe"
Write-Host "ADB device: $($script:Serial) | $model"
Write-Host "Runtime:    $runtimeDir"
Write-Host "Probe:      $ProbeOutput"

Invoke-Adb -Arguments @("install", "-r", $apk)
Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRuntime' && mkdir -p '$remoteRuntime' && rm -f '$remoteProbe'")
Invoke-Adb -Arguments @("push", (Join-Path $runtimeDir "."), "$remoteRuntime/")
Invoke-Adb -Arguments @("shell", "monkey", "-p", $ApplicationId, "1")

$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteProbe' ]; then echo ready; fi") -Capture) -join "").Trim()
    if ($check -eq "ready") { $ready = $true; break }
}
if (-not $ready) {
    throw "Quest player did not produce machine probe evidence. Inspect the headset and adb logcat before retrying; evidence was not fabricated."
}

Invoke-Adb -Arguments @("pull", $remoteProbe, $ProbeOutput)
if (-not (Test-Path -LiteralPath $ProbeOutput -PathType Leaf)) { throw "adb reported probe pull success but local evidence is missing: $ProbeOutput" }
try { $probe = Get-Content -LiteralPath $ProbeOutput -Raw | ConvertFrom-Json } catch { throw "Quest machine probe is not valid JSON: $ProbeOutput" }
if ([string]$probe.format -ne "bodyrig-renderer-probe" -or [int]$probe.version -ne 1 -or [string]$probe.platform -ne "android-quest-class" -or [string]$probe.unity_platform -ne "Android") {
    throw "Quest machine probe has the wrong format/platform."
}
if ([string]$probe.device_model -notmatch '(?i)quest|oculus') { throw "Quest machine probe does not identify Quest/Oculus hardware." }
if ([string]::IsNullOrWhiteSpace([string]$probe.build_guid)) { throw "Quest machine probe has no Unity build GUID." }
if ([string]$probe.active_renderer.name -ne $RendererName -or [string]$probe.active_renderer.version -ne $RendererVersion) {
    throw "Quest machine probe renderer identity differs from the reference build contract."
}
if ((Need-Sha256 ([string]$probe.runtime_manifest_sha256) "probe.runtime_manifest_sha256") -ne $actualRuntimeHash) {
    throw "Quest machine probe does not identify the Gate A runtime manifest bytes."
}

Write-Host "BodyRig Quest machine probe: PASS"
Write-Host "Machine evidence: $ProbeOutput"
Write-Host "The app remains available on the headset for human visual inspection."
Write-Host "Human visual attestation is still required with record-renderer-acceptance.ps1."
exit 0
