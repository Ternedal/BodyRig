param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [string]$UnityExe = "",
    [string]$AdbExe = "",
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Automatic Quest proof is Windows-orchestrated." }
$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [IO.Path]::GetFullPath($AcceptanceDir)
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

$script:AdbExe = $AdbExe
$script:Serial = $Serial
if ([string]::IsNullOrWhiteSpace($script:Serial)) {
    $devices = @(Invoke-Adb -Arguments @("devices") -Capture | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
    if ($devices.Count -ne 1) { throw "Expected exactly one online adb device; found $($devices.Count). Pass -Serial when needed." }
    $script:Serial = ($devices[0] -split '\s+')[0]
}
$model = ((Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") -Capture) -join "").Trim()
if ($model -notmatch '(?i)(quest|oculus)') { throw "Connected device is not Quest/Oculus-class: '$model'" }

$applicationId = [string]$contract.application_id
$remoteRoot = "/sdcard/Android/data/$applicationId/files/BodyRig"
$remoteQuality = "$remoteRoot/bodyrig-deformation-quality.json"
Invoke-Adb -Arguments @("shell", "rm", "-f", $remoteQuality)

$inner = Join-Path $repoRoot "run-reference-quest-renderer-probe.ps1"
try {
    $args = @{ AcceptanceDir = $AcceptanceDir; AdbExe = $AdbExe; Serial = $script:Serial }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $args.UnityExe = $UnityExe }
    & $inner @args
    if ($LASTEXITCODE -ne 0) { throw "Reference Quest renderer probe failed with exit code $LASTEXITCODE." }

    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Seconds 1
        $check = ((Invoke-Adb -Arguments @("shell", "sh", "-c", "if [ -f '$remoteQuality' ]; then echo ready; fi") -Capture) -join "").Trim()
        if ($check -eq "ready") { $ready = $true; break }
    }
    if (-not $ready) { throw "Quest automatic deformation quality receipt was not produced within the bounded wait." }

    $localQuality = Join-Path $AcceptanceDir "quest-evidence\quest-deformation-quality.json"
    if (Test-Path -LiteralPath $localQuality) { throw "Quest local quality receipt already exists: $localQuality" }
    $temp = "$localQuality.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        Invoke-Adb -Arguments @("pull", $remoteQuality, $temp)
        if (-not (Test-Path -LiteralPath $temp -PathType Leaf)) { throw "adb pull returned without a local Quest quality receipt." }
        try { $quality = Get-Content -LiteralPath $temp -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { throw "Quest automatic quality receipt is invalid JSON." }
        if ([string]$quality.format -ne "bodyrig-deformation-quality" -or [int]$quality.version -ne 1 -or [string]$quality.platform -ne "android-quest-class" -or $quality.machine_quality_pass -ne $true -or $quality.production_activation -ne $false) {
            throw "Quest automatic quality receipt is not a valid non-activating machine PASS."
        }
        Move-Item -LiteralPath $temp -Destination $localQuality
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }

    Write-Host "BODYRIG QUEST AUTOMATIC PHYSICAL PROOF: PASS"
    Write-Host "Quality receipt: $localQuality"
} finally {
    try { Invoke-Adb -Arguments @("shell", "am", "force-stop", $applicationId) } catch { }
}
exit 0
