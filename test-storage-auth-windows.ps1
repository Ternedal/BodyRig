param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [string]$BodyRigPython = "",
    [string]$Ffmpeg = "",
    [switch]$ResetConnections,
    [switch]$MarkPreReboot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig storage authentication proof is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }
if ($MarkPreReboot -and -not $ResetConnections) {
    throw "-MarkPreReboot requires -ResetConnections so the baseline proves a fresh SMB session."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$nativeHelper = Join-Path $repoRoot "storage-auth-native.ps1"
if (-not (Test-Path -LiteralPath $nativeHelper -PathType Leaf)) { throw "BodyRig native storage credential helper is missing: $nativeHelper" }
. $nativeHelper

$head = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $head.Count -ne 1 -or ([string]$head[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind storage proof to exact BodyRig Git HEAD."
}
$head = ([string]$head[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Storage authentication proof requires a clean BodyRig checkout." }

$configDir = Join-Path $env:LOCALAPPDATA "BodyRig\config"
$storageConfigPath = Join-Path $configDir "storage.json"
$stashConfigPath = Join-Path $configDir "stash.json"
$sessionProofPath = Join-Path $configDir "storage-session-proof.json"
$preRebootProofPath = Join-Path $configDir "storage-pre-reboot-proof.json"
$coldProofPath = Join-Path $configDir "storage-cold-boot-proof.json"

foreach ($required in @($storageConfigPath, $stashConfigPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required local BodyRig config is missing: $required" }
}
try { $storage = Get-Content -LiteralPath $storageConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Saved BodyRig storage configuration is unreadable JSON." }
try { $stash = Get-Content -LiteralPath $stashConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Saved BodyRig Stash configuration is unreadable JSON." }
if ([string]$storage.format -ne "bodyrig-local-storage-config" -or [int]$storage.version -ne 1) {
    throw "Saved storage configuration has an unexpected format/version."
}
if ([string]$stash.format -ne "bodyrig-local-stash-config" -or [int]$stash.version -ne 1) {
    throw "Saved Stash configuration has an unexpected format/version."
}

$storageHost = ([string]$storage.host).Trim()
$credentialTarget = ([string]$storage.credential_target).Trim().ToLowerInvariant()
$credentialGeneration = ([string]$storage.credential_generation).Trim().ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($storageHost) -or [string]::IsNullOrWhiteSpace($credentialTarget)) {
    throw "Saved storage configuration lacks host/credential target."
}
if ($credentialGeneration -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
    throw "Saved storage configuration lacks a canonical credential generation. Re-run the storage bootstrap."
}
try { $stashUri = [Uri]([string]$stash.url) }
catch { throw "Saved Stash URL is invalid." }
if (-not [string]::Equals($stashUri.Host, $storageHost, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Storage host '$storageHost' does not match the host used by Stash '$($stashUri.Host)'. Re-bootstrap the exact host instead of relying on an alias."
}
if (-not [string]::Equals($credentialTarget, $storageHost.ToLowerInvariant(), [StringComparison]::Ordinal)) {
    throw "Storage credential target does not exactly match the UNC host authority."
}
$maxPersist = [int](Get-BodyRigDomainCredentialMaxPersist)
if ($maxPersist -lt 2) {
    throw "Windows policy no longer permits LOCAL_MACHINE-or-stronger persistence for domain passwords."
}
if (-not (Test-BodyRigDomainCredential -Target $credentialTarget)) {
    throw "Windows Credential Manager has no domain-password credential for '$credentialTarget'."
}

if ($ResetConnections) {
    $connections = @(Get-SmbConnection -ErrorAction SilentlyContinue | Where-Object {
        [string]::Equals([string]$_.ServerName, $storageHost, [StringComparison]::OrdinalIgnoreCase)
    })
    $net = (Get-Command net.exe -ErrorAction Stop).Source
    foreach ($connection in $connections) {
        $share = [string]$connection.ShareName
        if ([string]::IsNullOrWhiteSpace($share)) { continue }
        $remote = "\\$storageHost\$share"
        $null = @(& $net use $remote /delete /y 2>&1)
    }
    Start-Sleep -Milliseconds 500
    $remaining = @(Get-SmbConnection -ErrorAction SilentlyContinue | Where-Object {
        [string]::Equals([string]$_.ServerName, $storageHost, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($remaining.Count -gt 0) {
        $names = @($remaining | ForEach-Object { "\\$storageHost\$([string]$_.ShareName)" }) -join ', '
        throw "Could not clear existing SMB sessions before proof: $names. Close programs holding storage files and retry."
    }
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = (Get-Command python -ErrorAction Stop).Source }
}
if (-not (Test-Path -LiteralPath $BodyRigPython -PathType Leaf)) { throw "BodyRig Python not found: $BodyRigPython" }
$expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualModule = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualModule.Count -ne 1 -or -not [string]::Equals([IO.Path]::GetFullPath(([string]$actualModule[0]).Trim()), $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python is not bound to this exact checkout."
}
if ([string]::IsNullOrWhiteSpace($Ffmpeg)) { $Ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source }

$secure = ConvertTo-SecureString ([string]$stash.api_key_dpapi)
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$stashApiKey = $null
$oldStashUrl = [Environment]::GetEnvironmentVariable("STASH_URL", "Process")
$oldStashKey = [Environment]::GetEnvironmentVariable("STASH_API_KEY", "Process")
try {
    $stashApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($stashApiKey)) { throw "Saved Stash API key could not be decrypted for this Windows user." }
    $env:STASH_URL = [string]$stash.url
    $env:STASH_API_KEY = $stashApiKey

    $pathConfig = Join-Path $repoRoot "configure-stash-path-map.ps1"
    & $pathConfig -PerformerId $PerformerId -ForceRefresh
    if ($LASTEXITCODE -ne 0) { throw "Stash path-map refresh failed." }
    if ([string]::IsNullOrWhiteSpace($env:BODYRIG_STASH_PATH_MAP)) {
        throw "Stash path-map refresh produced no readable SMB mapping."
    }

    $probeRaw = @(& $BodyRigPython -m bodyrig.stash_cli probe `
        --performer-id $PerformerId `
        --scene-limit 200 `
        --max-sources 3 `
        --ffmpeg $Ffmpeg `
        --decode-timeout 20 2>&1)
    if ($LASTEXITCODE -ne 0 -or $probeRaw.Count -ne 1) {
        throw "Real Stash-source decode proof failed: $($probeRaw -join ' ')"
    }
    try { $probe = ([string]$probeRaw[0]) | ConvertFrom-Json }
    catch { throw "Stash-source probe returned unreadable JSON." }
    if ($probe.ok -ne $true -or [string]$probe.performer.id -ne [string]$PerformerId -or [int]$probe.usable_source_count -lt 1) {
        throw "Stash-source probe did not prove a usable source for performer $PerformerId."
    }
} finally {
    $stashApiKey = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    [Environment]::SetEnvironmentVariable("STASH_URL", $oldStashUrl, "Process")
    [Environment]::SetEnvironmentVariable("STASH_API_KEY", $oldStashKey, "Process")
}

$boot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime().ToString("o")
$proof = [ordered]@{
    format = "bodyrig-storage-session-proof"
    version = 1
    bodyrig_revision = $head
    host = $storageHost
    credential_target = $credentialTarget
    credential_generation = $credentialGeneration
    performer_id = [string]$PerformerId
    boot_utc = $boot
    tested_utc = [DateTime]::UtcNow.ToString("o")
    existing_connections_reset = [bool]$ResetConnections
    credential_prompt_used = $false
    stash_path_map = $true
    real_stash_source_decode = $true
    usable_source_count = [int]$probe.usable_source_count
    decode_gate = [string]$probe.decode_gate
    maximum_supported_persist = $maxPersist
    secret_persisted_in_proof = $false
}
$temp = "$sessionProofPath.tmp-$([Guid]::NewGuid().ToString('N'))"
[IO.File]::WriteAllText($temp, (($proof | ConvertTo-Json -Depth 6) + "`n"), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $sessionProofPath -Force

if ($MarkPreReboot) {
    # A new baseline starts a new qualification cycle. Any prior cold-boot
    # counter is invalid even if host/username happen to be unchanged.
    Remove-Item -LiteralPath $coldProofPath -Force -ErrorAction SilentlyContinue
    $pre = [ordered]@{
        format = "bodyrig-storage-pre-reboot-proof"
        version = 1
        bodyrig_revision = $head
        host = $storageHost
        credential_target = $credentialTarget
        credential_generation = $credentialGeneration
        performer_id = [string]$PerformerId
        baseline_boot_utc = $boot
        tested_utc = [DateTime]::UtcNow.ToString("o")
        fresh_smb_session_proved = $true
        real_stash_source_decode = $true
        maximum_supported_persist = $maxPersist
        required_distinct_post_reboot_boots = 2
        secret_persisted_in_proof = $false
    }
    $preTemp = "$preRebootProofPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    [IO.File]::WriteAllText($preTemp, (($pre | ConvertTo-Json -Depth 6) + "`n"), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $preTemp -Destination $preRebootProofPath -Force
}

Write-Host "BodyRig storage authentication: PASS"
Write-Host "Host:                 $storageHost"
Write-Host "Credential cycle:     $credentialGeneration"
Write-Host "Fresh SMB session:    $([bool]$ResetConnections)"
Write-Host "Stash path map:       PASS"
Write-Host "Real source decode:   PASS ($([int]$probe.usable_source_count) usable source(s))"
Write-Host "Credential prompt:    FALSE"
Write-Host "Persist policy:       $maxPersist"
Write-Host "Boot:                 $boot"
if ($MarkPreReboot) { Write-Host "Pre-reboot baseline:  RECORDED" }
