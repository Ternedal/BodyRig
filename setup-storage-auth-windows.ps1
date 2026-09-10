param(
    [string]$StorageHost = "",
    [string]$UserName = "",
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig storage credential bootstrap is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$nativeHelper = Join-Path $PSScriptRoot "storage-auth-native.ps1"
if (-not (Test-Path -LiteralPath $nativeHelper -PathType Leaf)) { throw "BodyRig native storage credential helper is missing: $nativeHelper" }
. $nativeHelper

$configDir = Join-Path $env:LOCALAPPDATA "BodyRig\config"
$stashConfigPath = Join-Path $configDir "stash.json"
$storageConfigPath = Join-Path $configDir "storage.json"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

function Resolve-StorageHost {
    param([string]$Explicit)
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $candidate = $Explicit.Trim().TrimStart('\\').Split('\\')[0]
        if ($candidate -notmatch '^[A-Za-z0-9._:-]+$') { throw "Storage host contains unsupported characters." }
        return $candidate
    }
    if (-not (Test-Path -LiteralPath $stashConfigPath -PathType Leaf)) {
        throw "Storage host was not supplied and saved Stash configuration is missing."
    }
    try { $stash = Get-Content -LiteralPath $stashConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Saved Stash configuration is unreadable JSON." }
    if ([string]$stash.format -ne "bodyrig-local-stash-config" -or [int]$stash.version -ne 1) {
        throw "Saved Stash configuration has an unexpected format/version."
    }
    try { $uri = [Uri]([string]$stash.url) }
    catch { throw "Saved Stash URL is invalid." }
    if ([string]::IsNullOrWhiteSpace($uri.Host)) { throw "Saved Stash URL has no host." }
    return [string]$uri.Host
}

function Write-StorageConfig {
    param(
        [Parameter(Mandatory = $true)][bool]$CredentialWriteCompleted,
        [Parameter(Mandatory = $true)][string]$CredentialGeneration,
        [Parameter(Mandatory = $true)][string]$CredentialUserName
    )
    $config = [ordered]@{
        format = "bodyrig-local-storage-config"
        version = 1
        host = $StorageHost
        credential_target = $target
        credential_generation = $CredentialGeneration
        username = $CredentialUserName
        credential_store = "windows-credential-manager-domain-password"
        requested_persist = "local-machine"
        maximum_supported_persist = $maxPersist
        credential_write_completed = $CredentialWriteCompleted
        password_persisted_in_config = $false
        updated_utc = [DateTime]::UtcNow.ToString("o")
    }
    $temp = "$storageConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temp, (($config | ConvertTo-Json -Depth 4) + "`n"), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $storageConfigPath -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

$StorageHost = Resolve-StorageHost -Explicit $StorageHost
$target = $StorageHost.ToLowerInvariant()
$maxPersist = [int](Get-BodyRigDomainCredentialMaxPersist)
if ($maxPersist -lt 2) {
    throw "Windows policy only permits credential persistence level $maxPersist for domain passwords; BodyRig requires LOCAL_MACHINE (2) or stronger before claiming reboot persistence."
}

$alreadyExists = Test-BodyRigDomainCredential -Target $target
if ($alreadyExists -and -not $ReplaceExisting) {
    throw "A Windows domain credential already exists for '$target'. Re-run with -ReplaceExisting only if you intend to replace it."
}

if ([string]::IsNullOrWhiteSpace($UserName)) {
    $credential = Get-Credential -Message "BodyRig SMB login for \\$StorageHost"
} else {
    $credential = Get-Credential -UserName $UserName -Message "BodyRig SMB login for \\$StorageHost"
}
if ($null -eq $credential) { throw "Storage credential entry was cancelled." }

# Publish a new unqualified generation before touching the secret. If any later
# operation fails, canonical status sees credential_write_completed=false and
# cannot reuse old qualification evidence against changed or uncertain bytes.
$credentialGeneration = [Guid]::NewGuid().ToString("D").ToLowerInvariant()
Write-StorageConfig -CredentialWriteCompleted $false -CredentialGeneration $credentialGeneration -CredentialUserName $credential.UserName

# Old evidence must be invalidated before the native credential changes. A
# failure to remove an existing proof is fatal; the secret remains untouched.
foreach ($proofName in @(
    "storage-session-proof.json",
    "storage-pre-reboot-proof.json",
    "storage-cold-boot-proof.json"
)) {
    $proofPath = Join-Path $configDir $proofName
    if (Test-Path -LiteralPath $proofPath) {
        Remove-Item -LiteralPath $proofPath -Force -ErrorAction Stop
    }
}

Set-BodyRigDomainCredential -Target $target -UserName $credential.UserName -Password $credential.Password
if (-not (Test-BodyRigDomainCredential -Target $target)) {
    throw "Windows Credential Manager did not retain the SMB credential."
}

# Only this final atomic metadata publication makes the new credential cycle
# eligible for fresh-session testing. If it fails, the false state above stays
# authoritative and the pipeline remains blocked.
Write-StorageConfig -CredentialWriteCompleted $true -CredentialGeneration $credentialGeneration -CredentialUserName $credential.UserName

Write-Host "BodyRig storage credential: SAVED"
Write-Host "Host:              $StorageHost"
Write-Host "Credential target: $target"
Write-Host "Credential cycle:  $credentialGeneration"
Write-Host "Persist policy:    $maxPersist (LOCAL_MACHINE=2, ENTERPRISE=3)"
Write-Host "Prior proofs:      INVALIDATED"
Write-Host "Secret in config:  FALSE"
Write-Host "Next: run .\test-storage-auth-windows.ps1 -PerformerId <id> -ResetConnections -MarkPreReboot to prove a fresh SMB session before reboot."
