param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Automatic Quest proof is Windows-orchestrated." }
$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $BodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) { throw "BodyRig Python not found: $BodyRigPython" }
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path
$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualModuleRaw = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualModuleRaw.Count -ne 1) { throw "BodyRig Python could not prove checkout-bound import authority for Quest automatic proof." }
$actualModulePath = ([string]$actualModuleRaw[0]).Trim()
if (-not (Test-Path -LiteralPath $actualModulePath -PathType Leaf)) { throw "BodyRig Python returned an invalid bodyrig import path for Quest automatic proof." }
$actualModule = (Resolve-Path -LiteralPath $actualModulePath).Path
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from unexpected location: $actualModule. Expected checkout authority: $expectedModule"
}

$contractPath = Join-Path $repoRoot "reference-renderer\renderer-contract.json"
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is not valid JSON: $contractPath" }
$pinnedAdb = Join-Path "C:\Program Files\Unity\Hub\Editor\$([string]$contract.unity_editor_version)\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools" "adb.exe"
if (-not (Test-Path -LiteralPath $pinnedAdb -PathType Leaf)) { throw "Pinned adb not found: $pinnedAdb" }
$pinnedAdb = (Resolve-Path -LiteralPath $pinnedAdb).Path
if (-not [string]::IsNullOrWhiteSpace($AdbExe)) {
    $requested = (Resolve-Path -LiteralPath $AdbExe).Path
    if (-not [string]::Equals($requested, $pinnedAdb, [StringComparison]::OrdinalIgnoreCase)) { throw "Automatic Quest proof refuses non-pinned adb: $requested" }
}
$AdbExe = $pinnedAdb

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

function Get-AutomaticStatus {
    $raw = @(& $BodyRigPython -m bodyrig.automatic_activation_status --acceptance-dir $AcceptanceDir --repo-root $repoRoot --json 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -or $raw.Count -ne 1) {
        throw "Automatic activation status failed for Quest proof: $($raw -join [Environment]::NewLine)"
    }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "Automatic activation status returned invalid JSON for Quest proof." }
}

function Test-RemoteQualityReady {
    $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$script:RemoteQuality' ]; then echo ready; fi") -Capture) -join "").Trim()
    return $check -eq "ready"
}

function Wait-RemoteQuality {
    param([switch]$RelaunchIfMissing)
    if (-not (Test-RemoteQualityReady) -and $RelaunchIfMissing) {
        Write-Host "Quest automatic quality receipt is not present yet; relaunching the already-installed exact reference app without rebuilding."
        Invoke-Adb -Arguments @("shell", "monkey", "-p", $script:ApplicationId, "1")
    }
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-RemoteQualityReady) { return }
        Start-Sleep -Seconds 1
    }
    throw "Quest automatic deformation quality receipt was not produced within the bounded wait."
}

$script:AdbExe = $AdbExe
$script:Serial = $Serial
if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(Invoke-Adb -Arguments @("devices") -Capture | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
    if ($devices.Count -ne 1) { throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when needed." }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(quest|oculus)') { throw "Connected device is not Quest/Oculus-class: '$model'" }

$script:ApplicationId = [string]$contract.application_id
$remoteRoot = "/sdcard/Android/data/$($script:ApplicationId)/files/BodyRig"
$script:RemoteQuality = "$remoteRoot/bodyrig-deformation-quality.json"
$evidenceDir = Join-Path $AcceptanceDir "quest-evidence"
$localProbe = Join-Path $evidenceDir "quest-probe.json"
$localDeformation = Join-Path $evidenceDir "quest-deformation-probe.json"
$localQuality = Join-Path $evidenceDir "quest-deformation-quality.json"
$probeExists = Test-Path -LiteralPath $localProbe -PathType Leaf
$deformationExists = Test-Path -LiteralPath $localDeformation -PathType Leaf
$qualityExists = Test-Path -LiteralPath $localQuality -PathType Leaf
if ($probeExists -ne $deformationExists) { throw "Quest automatic local probe/deformation evidence is incomplete; refusing recovery." }
if ($qualityExists -and -not ($probeExists -and $deformationExists)) { throw "Quest automatic quality exists without its committed probe/deformation pair." }
if ($qualityExists) { throw "Quest automatic quality receipt already exists. Use run-automatic-production-activation.ps1 to validate and continue the chain." }
$recoverQualityOnly = $probeExists -and $deformationExists

$inner = Join-Path $repoRoot "run-reference-quest-renderer-probe.ps1"
try {
    if ($recoverQualityOnly) {
        $before = Get-AutomaticStatus
        if ([string]$before.stage -ne "quest-quality") {
            throw "Existing Quest probe/deformation pair is not an authority-valid automatic quality recovery state: $([string]$before.stage)"
        }
        Write-Host "BodyRig Quest automatic proof: reusing committed probe/deformation; recovering quality receipt only."
        Wait-RemoteQuality -RelaunchIfMissing
    } else {
        Invoke-Adb -Arguments @("shell", "rm", "-f", $script:RemoteQuality)
        $args = @{ AcceptanceDir = $AcceptanceDir; AdbExe = $AdbExe; Serial = $script:Serial }
        if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }
        & $inner @args
        if ($LASTEXITCODE -ne 0) { throw "Reference Quest renderer probe failed with exit code $LASTEXITCODE." }
        Wait-RemoteQuality -RelaunchIfMissing
    }

    $temp = "$localQuality.$([Guid]::NewGuid().ToString('N')).tmp"
    $qualityCommitted = $false
    try {
        Invoke-Adb -Arguments @("pull", $script:RemoteQuality, $temp)
        if (-not (Test-Path -LiteralPath $temp -PathType Leaf)) { throw "adb pull returned without a local Quest quality receipt." }
        try { $quality = Get-Content -LiteralPath $temp -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { throw "Quest automatic quality receipt is invalid JSON." }
        if ([string]$quality.format -ne "bodyrig-deformation-quality" -or [int]$quality.version -ne 1 -or [string]$quality.platform -ne "android-quest-class" -or $quality.machine_quality_pass -ne $true -or $quality.production_activation -ne $false) {
            throw "Quest automatic quality receipt is not a valid non-activating machine PASS."
        }
        Move-Item -LiteralPath $temp -Destination $localQuality
        $qualityCommitted = $true
        $after = Get-AutomaticStatus
        if ([string]$after.stage -notin @("release", "complete")) {
            throw "Quest quality receipt did not produce an authority-valid downstream automatic stage: $([string]$after.stage)"
        }
    } catch {
        if ($qualityCommitted -and (Test-Path -LiteralPath $localQuality -PathType Leaf)) {
            Remove-Item -LiteralPath $localQuality -Force
        }
        throw
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }

    Write-Host "BODYRIG QUEST AUTOMATIC PHYSICAL PROOF: PASS"
    Write-Host "Quality receipt: $localQuality"
    if ($recoverQualityOnly) { Write-Host "Quest renderer rebuild: skipped (reused exact committed probe/deformation authority)" }
} finally {
    try { Invoke-Adb -Arguments @("shell", "am", "force-stop", $script:ApplicationId) } catch { }
}
exit 0
