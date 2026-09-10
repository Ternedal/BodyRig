param(
    [string]$PerformerId = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig storage authentication status is Windows-only."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$nativeHelper = Join-Path $PSScriptRoot "storage-auth-native.ps1"
if (-not (Test-Path -LiteralPath $nativeHelper -PathType Leaf)) { throw "BodyRig native storage credential helper is missing: $nativeHelper" }
. $nativeHelper

$configDir = Join-Path $env:LOCALAPPDATA "BodyRig\config"
$storagePath = Join-Path $configDir "storage.json"
$stashPath = Join-Path $configDir "stash.json"
$prePath = Join-Path $configDir "storage-pre-reboot-proof.json"
$coldPath = Join-Path $configDir "storage-cold-boot-proof.json"

function Emit-Status {
    param(
        [string]$State,
        [string]$Stage,
        [string]$Message,
        [string]$NextCommand = "",
        [string]$Host = "",
        [int]$Passed = 0,
        [int]$Required = 2,
        [bool]$CredentialPresent = $false
    )
    $result = [ordered]@{
        format = "bodyrig-storage-auth-status"
        version = 1
        state = $State
        stage = $Stage
        host = $Host
        credential_present = $CredentialPresent
        cold_boots_passed = $Passed
        cold_boots_required = $Required
        qualified = ($State -eq "qualified")
        secret_exposed = $false
        next_command = $(if ([string]::IsNullOrWhiteSpace($NextCommand)) { $null } else { $NextCommand })
        message = $Message
    }
    if ($Json) {
        $result | ConvertTo-Json -Depth 5 -Compress
    } else {
        $credentialText = if ($CredentialPresent) { "PRESENT" } else { "MISSING" }
        Write-Host "BodyRig storage auth: $($State.ToUpperInvariant())"
        if (-not [string]::IsNullOrWhiteSpace($Host)) { Write-Host "Host:       $Host" }
        Write-Host "Credential: $credentialText"
        Write-Host "Cold boots: $Passed/$Required"
        Write-Host $Message
        if ($null -ne $result.next_command) {
            Write-Host "Next command:"
            Write-Host $result.next_command
        }
    }
    return
}

if (-not (Test-Path -LiteralPath $storagePath -PathType Leaf)) {
    Emit-Status -State "required" -Stage "credential-bootstrap" -Message "No persistent SMB credential has been configured for BodyRig." -NextCommand ".\setup-storage-auth-windows.ps1"
    exit 0
}
if (-not (Test-Path -LiteralPath $stashPath -PathType Leaf)) {
    Emit-Status -State "blocked" -Stage "stash-config" -Message "Storage config exists but saved Stash config is missing; exact host authority cannot be proven."
    exit 0
}
try { $storage = Get-Content -LiteralPath $storagePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Emit-Status -State "blocked" -Stage "storage-config" -Message "Saved storage config is unreadable JSON."; exit 0 }
try { $stash = Get-Content -LiteralPath $stashPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Emit-Status -State "blocked" -Stage "stash-config" -Message "Saved Stash config is unreadable JSON."; exit 0 }
if ([string]$storage.format -ne "bodyrig-local-storage-config" -or [int]$storage.version -ne 1) {
    Emit-Status -State "blocked" -Stage "storage-config" -Message "Saved storage config has an unexpected format/version."
    exit 0
}
try { $stashUri = [Uri]([string]$stash.url) }
catch { Emit-Status -State "blocked" -Stage "stash-config" -Message "Saved Stash URL is invalid."; exit 0 }
$hostName = ([string]$storage.host).Trim()
$target = ([string]$storage.credential_target).Trim().ToLowerInvariant()
$credentialGeneration = ([string]$storage.credential_generation).Trim().ToLowerInvariant()
if (
    [string]::IsNullOrWhiteSpace($hostName) -or
    $credentialGeneration -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
    -not [string]::Equals($stashUri.Host, $hostName, [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals($target, $hostName.ToLowerInvariant(), [StringComparison]::Ordinal)
) {
    Emit-Status -State "blocked" -Stage "host-authority" -Host $hostName -Message "Storage config lacks a canonical credential generation or Storage/Stash host authority differs. Re-bootstrap the exact UNC host."
    exit 0
}

$maxPersist = [int](Get-BodyRigDomainCredentialMaxPersist)
if ($maxPersist -lt 2) {
    Emit-Status -State "blocked" -Stage "windows-policy" -Host $hostName -Message "Windows policy permits persistence level $maxPersist for domain passwords; LOCAL_MACHINE (2) or stronger is required."
    exit 0
}
$credentialPresent = Test-BodyRigDomainCredential -Target $target
if (-not $credentialPresent) {
    Emit-Status -State "required" -Stage "credential-bootstrap" -Host $hostName -CredentialPresent $false -Message "Storage config exists, but the Windows Credential Manager credential is missing." -NextCommand ".\setup-storage-auth-windows.ps1 -ReplaceExisting"
    exit 0
}

$performerArg = if ([string]::IsNullOrWhiteSpace($PerformerId)) { "<performer-id>" } else { $PerformerId.Trim() }
if (-not (Test-Path -LiteralPath $prePath -PathType Leaf)) {
    $next = ".\test-storage-auth-windows.ps1 -PerformerId '$performerArg' -ResetConnections -MarkPreReboot"
    Emit-Status -State "configured" -Stage "fresh-session-proof" -Host $hostName -CredentialPresent $true -Message "Credential is persisted, but a fresh-session Stash-source proof has not been recorded." -NextCommand $next
    exit 0
}
try { $pre = Get-Content -LiteralPath $prePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Emit-Status -State "blocked" -Stage "pre-reboot-proof" -Host $hostName -CredentialPresent $true -Message "Pre-reboot storage proof is unreadable JSON."; exit 0 }
if (
    [string]$pre.format -ne "bodyrig-storage-pre-reboot-proof" -or
    [int]$pre.version -ne 1 -or
    [string]$pre.host -ne $hostName -or
    [string]$pre.credential_target -ne $target -or
    [string]$pre.credential_generation -ne $credentialGeneration -or
    $pre.fresh_smb_session_proved -ne $true -or
    $pre.real_stash_source_decode -ne $true -or
    [int]$pre.maximum_supported_persist -lt 2
) {
    Emit-Status -State "blocked" -Stage "pre-reboot-proof" -Host $hostName -CredentialPresent $true -Message "Pre-reboot proof does not match the current credential generation."
    exit 0
}

$required = [int]$pre.required_distinct_post_reboot_boots
if ($required -lt 2) { $required = 2 }
$passed = 0
$cold = $null
if (Test-Path -LiteralPath $coldPath -PathType Leaf) {
    try { $cold = Get-Content -LiteralPath $coldPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { Emit-Status -State "blocked" -Stage "cold-boot-proof" -Host $hostName -CredentialPresent $true -Message "Cold-boot proof is unreadable JSON."; exit 0 }
    if (
        [string]$cold.format -ne "bodyrig-storage-cold-boot-proof" -or
        [int]$cold.version -ne 1 -or
        [string]$cold.host -ne $hostName -or
        [string]$cold.credential_target -ne $target -or
        [string]$cold.credential_generation -ne $credentialGeneration -or
        [string]$cold.baseline_boot_utc -ne [string]$pre.baseline_boot_utc
    ) {
        Emit-Status -State "blocked" -Stage "cold-boot-proof" -Host $hostName -CredentialPresent $true -Message "Cold-boot proof does not match the current credential generation."
        exit 0
    }
    $passed = [int]$cold.successful_boot_count
    if ($cold.qualified -eq $true -and $passed -ge $required) {
        Emit-Status -State "qualified" -Stage "complete" -Host $hostName -CredentialPresent $true -Passed $passed -Required $required -Message "Persistent SMB authentication has been proven across the required distinct Windows boots with real Stash-source decode and zero prompts."
        exit 0
    }
}

$currentBootText = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime().ToString("o")
if ($null -ne $cold -and @($cold.successful_boots | Where-Object { [string]$_.boot_utc -eq $currentBootText }).Count -gt 0) {
    Emit-Status -State "reboot-required" -Stage "cold-boot-proof" -Host $hostName -CredentialPresent $true -Passed $passed -Required $required -Message "This boot has already been counted. Reboot Windows before the next persistence verification."
    exit 0
}
try { $baselineBoot = [DateTimeOffset]::Parse([string]$pre.baseline_boot_utc).UtcDateTime }
catch { Emit-Status -State "blocked" -Stage "pre-reboot-proof" -Host $hostName -CredentialPresent $true -Passed $passed -Required $required -Message "Pre-reboot boot timestamp is invalid."; exit 0 }
$currentBoot = [DateTimeOffset]::Parse($currentBootText).UtcDateTime
if ($currentBoot -le $baselineBoot) {
    Emit-Status -State "reboot-required" -Stage "cold-boot-proof" -Host $hostName -CredentialPresent $true -Passed $passed -Required $required -Message "Fresh-session proof passed. Reboot Windows before recording the first cold-boot verification."
    exit 0
}
$nextVerify = ".\verify-storage-auth-after-reboot.ps1 -PerformerId '$performerArg'"
Emit-Status -State "verify-now" -Stage "cold-boot-proof" -Host $hostName -CredentialPresent $true -Passed $passed -Required $required -Message "Current boot has not yet been counted; run the no-prompt real-source verification now." -NextCommand $nextVerify
