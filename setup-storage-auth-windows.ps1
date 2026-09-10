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
Set-BodyRigDomainCredential -Target $target -UserName $credential.UserName -Password $credential.Password
if (-not (Test-BodyRigDomainCredential -Target $target)) {
    throw "Windows Credential Manager did not retain the SMB credential."
}

# A credential replacement invalidates every previous reboot qualification for
# the same host. Clear proofs immediately after the native credential changes,
# before writing the new generation metadata, so a partial config failure can
# never leave an old QUALIFIED receipt attached to new secret bytes.
foreach ($proofName in @(
    "storage-session-proof.json",
    "storage-pre-reboot-proof.json",
    "storage-cold-boot-proof.json"
)) {
    Remove-Item -LiteralPath (Join-Path $configDir $proofName) -Force -ErrorAction SilentlyContinue
}
$credentialGeneration = [Guid]::NewGuid().ToString("D").ToLowerInvariant()

$config = [ordered]@{
    format = "bodyrig-local-storage-config"
    version = 1
    host = $StorageHost
    credential_target = $target
    credential_generation = $credentialGeneration
    username = $credential.UserName
    credential_store = "windows-credential-manager-domain-password"
    requested_persist = "local-machine"
    maximum_supported_persist = $maxPersist
    password_persisted_in_config = $false
    updated_utc = [DateTime]::UtcNow.ToString("o")
}
$temp = "$storageConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
[IO.File]::WriteAllText($temp, (($config | ConvertTo-Json -Depth 4) + "`n"), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $storageConfigPath -Force

Write-Host "BodyRig storage credential: SAVED"
Write-Host "Host:              $StorageHost"
Write-Host "Credential target: $target"
Write-Host "Credential cycle:  $credentialGeneration"
Write-Host "Persist policy:    $maxPersist (LOCAL_MACHINE=2, ENTERPRISE=3)"
Write-Host "Prior proofs:      INVALIDATED"
Write-Host "Secret in config:  FALSE"
Write-Host "Next: run .\test-storage-auth-windows.ps1 -PerformerId <id> -ResetConnections -MarkPreReboot to prove a fresh SMB session before reboot."
