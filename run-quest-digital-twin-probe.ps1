param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig M5 physical evidence path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for canonical BodyRig M5 physical evidence."
}
if ($null -eq (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 executable (pwsh) was not found."
}

$ApplicationId = "dk.ternedal.bodyrig.reference"
$RendererName = "BodyRig Reference Renderer"
$RendererVersion = "reference-v1/univrm-0.131.2"

function Need-Revision([string]$Value, [string]$Label) {
    $normalized = $Value.ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not a canonical 40-character Git SHA." }
    return $normalized
}
function Resolve-BodyRigPython {
    $venv = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return (Resolve-Path -LiteralPath $venv).Path }
    return (Get-Command python -ErrorAction Stop).Source
}
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

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
$CompositionAuthorityDir = [System.IO.Path]::GetFullPath($CompositionAuthorityDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) { throw "Acceptance directory not found: $AcceptanceDir" }
if (-not (Test-Path -LiteralPath $CompositionAuthorityDir -PathType Container)) { throw "M4 composition authority directory not found: $CompositionAuthorityDir" }

$acceptancePath = Join-Path $AcceptanceDir "bodyrig-acceptance.json"
$runtimeDir = Join-Path $AcceptanceDir "runtime"
$runtimeManifest = Join-Path $runtimeDir "runtime-manifest.json"
$authorityPath = Join-Path $CompositionAuthorityDir "authority.json"
$embodimentPath = Join-Path $CompositionAuthorityDir "embodiment-probe.json"
foreach ($required in @($acceptancePath, $runtimeManifest, $authorityPath, $embodimentPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required M5 evidence input missing: $required" }
}

try { $acceptance = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Gate A acceptance report is not valid JSON: $acceptancePath" }
$acceptedRevision = Need-Revision ([string]$acceptance.bodyrig_revision) "acceptance.bodyrig_revision"
$currentHeadLines = @(& git -C $script:RepoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$currentHead = Need-Revision ([string]$currentHeadLines[0].Trim()) "current BodyRig HEAD"
if ($currentHead -ne $acceptedRevision) { throw "Current BodyRig checkout does not match Gate A revision; refusing M5 Quest evidence." }
$dirty = @(& git -C $script:RepoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; M5 Quest evidence requires the exact clean Gate A revision." }

$contractPath = Join-Path $script:RepoRoot "reference-renderer\renderer-contract.json"
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is not valid JSON: $contractPath" }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) { throw "Unsupported reference renderer contract format/version." }
if ([string]$contract.application_id -ne $ApplicationId) { throw "Reference renderer contract has an unsupported Quest application id." }
if ([string]$contract.renderer_name -ne $RendererName -or [string]$contract.renderer_version -ne $RendererVersion) { throw "Quest renderer identity differs from the pinned reference renderer contract." }

$pinnedAdb = Join-Path "C:\Program Files\Unity\Hub\Editor\$([string]$contract.unity_editor_version)\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe"
if (-not (Test-Path -LiteralPath $pinnedAdb -PathType Leaf)) { throw "Pinned Unity Android adb not found: $pinnedAdb" }
$pinnedAdb = (Resolve-Path -LiteralPath $pinnedAdb).Path
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    if (-not (Test-Path -LiteralPath $AdbExe -PathType Leaf)) { throw "Requested adb executable not found: $AdbExe" }
    $requestedAdb = (Resolve-Path -LiteralPath $AdbExe).Path
    if (-not [string]::Equals($requestedAdb, $pinnedAdb, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "M5 Quest evidence requires the pinned Unity Android SDK adb.exe; refusing alternate adb: $requestedAdb"
    }
}
$script:AdbExe = $pinnedAdb
$script:Serial = $Serial

if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(Invoke-Adb -Arguments @("devices") -Capture | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
    if ($devices.Count -ne 1) { throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when multiple devices are attached." }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)quest|oculus') { throw "Connected adb device is not Quest/Oculus-class: '$model'" }

$finalEvidence = Join-Path $AcceptanceDir "digital-twin-quest-evidence"
if (Test-Path -LiteralPath $finalEvidence) { throw "M5 Quest evidence is create-only: $finalEvidence" }
$attemptDir = Join-Path $AcceptanceDir (".bodyrig-m5-quest-attempt-" + [Guid]::NewGuid().ToString("N"))
$python = Resolve-BodyRigPython
$previousPythonPath = $env:PYTHONPATH
$committed = $false

try {
    $env:PYTHONPATH = $script:RepoRoot
    $imported = (& $python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not import BodyRig from the operator checkout." }
    $expectedRoot = [System.IO.Path]::GetFullPath($script:RepoRoot).TrimEnd('\') + '\'
    if (-not ([System.IO.Path]::GetFullPath($imported)).StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Python imported BodyRig outside the current checkout: $imported"
    }

    & $python -m bodyrig.digital_twin_platform_acceptance_cli prepare `
        --composition-authority-dir $CompositionAuthorityDir `
        --acceptance-dir $AcceptanceDir `
        --platform android-quest-class `
        --output-dir $attemptDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create exact M5 Quest platform input." }

    $rendererRoot = Join-Path $script:RepoRoot "reference-renderer"
    $buildScript = Join-Path $rendererRoot "build-reference-renderer.ps1"
    $apk = Join-Path $rendererRoot "Builds\Quest\BodyRigReferenceProbe.apk"
    if (-not $SkipBuild) {
        $buildDir = Split-Path -Parent $apk
        if (Test-Path -LiteralPath $buildDir) { Remove-Item -LiteralPath $buildDir -Recurse -Force }
        $buildArgs = @{ Platform = "Quest"; Output = $apk }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $buildArgs.UnityExe = $UnityExe }
        & $buildScript @buildArgs
        if ($LASTEXITCODE -ne 0) { throw "BodyRig Quest reference renderer build failed with exit code $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw "Built Quest reference renderer APK not found: $apk" }

    $remoteRoot = "/sdcard/Android/data/$ApplicationId/files/BodyRig"
    $remoteRuntime = "$remoteRoot/runtime"
    $remoteTwin = "$remoteRoot/digital-twin"
    $remoteRealization = "$remoteTwin/realization.json"
    $remoteProbe = "$remoteRoot/bodyrig-renderer-probe.json"
    $remoteDeformation = "$remoteRoot/bodyrig-deformation-probe.json"

    Write-Host "BodyRig M5 Quest digital-twin realization"
    Write-Host "Revision:      $acceptedRevision"
    Write-Host "ADB authority: $($script:AdbExe)"
    Write-Host "ADB device:    $($script:Serial) | $model"
    Write-Host "M4 authority:  $CompositionAuthorityDir"
    Write-Host "Staging:       $attemptDir"

    Invoke-Adb -Arguments @("install", "-r", $apk)
    Invoke-Adb -Arguments @("shell", "sh", "-c", "rm -rf '$remoteRuntime' '$remoteTwin' && mkdir -p '$remoteRuntime' '$remoteTwin' && rm -f '$remoteProbe' '$remoteDeformation'")
    Invoke-Adb -Arguments @("push", (Join-Path $runtimeDir "."), "$remoteRuntime/")
    Invoke-Adb -Arguments @("push", (Join-Path $attemptDir "platform-input.json"), "$remoteTwin/platform-input.json")
    Invoke-Adb -Arguments @("push", (Join-Path $attemptDir "motor-state.json"), "$remoteTwin/motor-state.json")
    Invoke-Adb -Arguments @("push", $authorityPath, "$remoteTwin/composition-authority.json")
    Invoke-Adb -Arguments @("push", $embodimentPath, "$remoteTwin/embodiment-probe.json")
    Invoke-Adb -Arguments @("shell", "monkey", "-p", $ApplicationId, "1")

    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Seconds 1
        $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteRealization' ] && [ -f '$remoteProbe' ] && [ -f '$remoteDeformation' ]; then echo ready; fi") -Capture) -join "").Trim()
        if ($check -eq "ready") { $ready = $true; break }
    }
    if (-not $ready) { throw "Quest player did not produce complete M5 realization evidence; inspect headset/logcat before retrying. Local canonical evidence was not committed." }

    Invoke-Adb -Arguments @("pull", $remoteRealization, (Join-Path $attemptDir "realization.json"))
    Invoke-Adb -Arguments @("pull", $remoteProbe, (Join-Path $attemptDir "runtime-probe.json"))
    Invoke-Adb -Arguments @("pull", $remoteDeformation, (Join-Path $attemptDir "runtime-deformation-probe.json"))

    & $python -m bodyrig.digital_twin_platform_acceptance_cli validate `
        --composition-authority-dir $CompositionAuthorityDir `
        --acceptance-dir $AcceptanceDir `
        --platform android-quest-class `
        --evidence-dir $attemptDir
    if ($LASTEXITCODE -ne 0) { throw "M5 Quest realization failed transitive readback validation." }

    Move-Item -LiteralPath $attemptDir -Destination $finalEvidence
    $committed = $true
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container)) {
        Remove-Item -LiteralPath $attemptDir -Recurse -Force
    }
}

Write-Host "BodyRig M5 Quest digital-twin evidence: PASS"
Write-Host "Evidence directory: $finalEvidence"
Write-Host "This is non-activating M5 machine evidence; M6 remains required."
exit 0
