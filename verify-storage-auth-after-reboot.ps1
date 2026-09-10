param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [string]$BodyRigPython = "",
    [string]$Ffmpeg = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig post-reboot storage verification is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$configDir = Join-Path $env:LOCALAPPDATA "BodyRig\config"
$storagePath = Join-Path $configDir "storage.json"
$prePath = Join-Path $configDir "storage-pre-reboot-proof.json"
$coldPath = Join-Path $configDir "storage-cold-boot-proof.json"
$sessionPath = Join-Path $configDir "storage-session-proof.json"
foreach ($requiredPath in @($storagePath, $prePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required storage qualification state is missing: $requiredPath"
    }
}
try { $storage = Get-Content -LiteralPath $storagePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Saved storage configuration is unreadable JSON." }
try { $pre = Get-Content -LiteralPath $prePath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Pre-reboot storage proof is unreadable JSON." }
if ([string]$storage.format -ne "bodyrig-local-storage-config" -or [int]$storage.version -ne 1) {
    throw "Saved storage configuration has an unexpected format/version."
}
$credentialGeneration = ([string]$storage.credential_generation).Trim().ToLowerInvariant()
if ($credentialGeneration -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
    throw "Saved storage configuration lacks a canonical credential generation."
}
if (
    [string]$pre.format -ne "bodyrig-storage-pre-reboot-proof" -or
    [int]$pre.version -ne 1 -or
    $pre.fresh_smb_session_proved -ne $true -or
    $pre.real_stash_source_decode -ne $true -or
    $pre.secret_persisted_in_proof -ne $false
) {
    throw "Pre-reboot storage proof has an invalid authority boundary."
}
if (
    [string]$pre.host -ne [string]$storage.host -or
    [string]$pre.credential_target -ne [string]$storage.credential_target -or
    [string]$pre.credential_generation -ne $credentialGeneration
) {
    throw "Pre-reboot storage proof belongs to a different credential generation. Re-run the fresh-session baseline."
}
if ([string]$pre.performer_id -ne [string]$PerformerId) {
    throw "Pre-reboot storage proof belongs to performer $($pre.performer_id), not $PerformerId."
}

$currentBoot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime()
try { $baselineBoot = [DateTimeOffset]::Parse([string]$pre.baseline_boot_utc).UtcDateTime }
catch { throw "Pre-reboot proof has an invalid baseline boot timestamp." }
if ($currentBoot -le $baselineBoot) {
    throw "Windows has not rebooted since the pre-reboot proof. A cold-boot verification cannot be recorded yet."
}
$currentBootText = $currentBoot.ToString("o")

$testScript = Join-Path $PSScriptRoot "test-storage-auth-windows.ps1"
$argsList = @("-PerformerId", $PerformerId)
if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $argsList += @("-BodyRigPython", $BodyRigPython) }
if (-not [string]::IsNullOrWhiteSpace($Ffmpeg)) { $argsList += @("-Ffmpeg", $Ffmpeg) }
& $testScript @argsList
if ($LASTEXITCODE -ne 0) { throw "Post-reboot storage authentication test failed." }

if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) { throw "Post-reboot test did not write its session proof." }
try { $session = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Post-reboot storage session proof is unreadable JSON." }
if (
    [string]$session.format -ne "bodyrig-storage-session-proof" -or
    [int]$session.version -ne 1 -or
    [string]$session.host -ne [string]$pre.host -or
    [string]$session.credential_target -ne [string]$pre.credential_target -or
    [string]$session.credential_generation -ne $credentialGeneration -or
    [string]$session.performer_id -ne [string]$PerformerId -or
    $session.credential_prompt_used -ne $false -or
    $session.stash_path_map -ne $true -or
    $session.real_stash_source_decode -ne $true -or
    $session.secret_persisted_in_proof -ne $false
) {
    throw "Post-reboot storage session proof did not preserve the pre-reboot credential authority."
}
if ([string]$session.boot_utc -ne $currentBootText) {
    throw "Post-reboot test was not recorded in the current Windows boot session."
}

$successfulBoots = @()
if (Test-Path -LiteralPath $coldPath -PathType Leaf) {
    try { $cold = Get-Content -LiteralPath $coldPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Existing cold-boot qualification is unreadable JSON." }
    if (
        [string]$cold.format -ne "bodyrig-storage-cold-boot-proof" -or
        [int]$cold.version -ne 1 -or
        [string]$cold.host -ne [string]$pre.host -or
        [string]$cold.credential_target -ne [string]$pre.credential_target -or
        [string]$cold.credential_generation -ne $credentialGeneration -or
        [string]$cold.performer_id -ne [string]$PerformerId -or
        [string]$cold.baseline_boot_utc -ne [string]$pre.baseline_boot_utc
    ) {
        throw "Existing cold-boot qualification belongs to a different storage authority."
    }
    $successfulBoots = @($cold.successful_boots)
}

if (@($successfulBoots | Where-Object { [string]$_.boot_utc -eq $currentBootText }).Count -gt 0) {
    throw "This Windows boot session has already been counted. Reboot again before recording another qualification boot."
}
$successfulBoots += [ordered]@{
    boot_utc = $currentBootText
    tested_utc = [DateTime]::UtcNow.ToString("o")
    credential_prompt_used = $false
    stash_path_map = $true
    real_stash_source_decode = $true
    usable_source_count = [int]$session.usable_source_count
}

$required = [int]$pre.required_distinct_post_reboot_boots
if ($required -lt 2) { throw "Pre-reboot proof weakened the required cold-boot count." }
$qualified = $successfulBoots.Count -ge $required
$proof = [ordered]@{
    format = "bodyrig-storage-cold-boot-proof"
    version = 1
    host = [string]$pre.host
    credential_target = [string]$pre.credential_target
    credential_generation = $credentialGeneration
    performer_id = [string]$PerformerId
    baseline_boot_utc = [string]$pre.baseline_boot_utc
    required_distinct_post_reboot_boots = $required
    successful_boots = @($successfulBoots)
    successful_boot_count = $successfulBoots.Count
    qualified = [bool]$qualified
    credential_prompt_permitted = $false
    real_stash_source_decode_required = $true
    secret_persisted_in_proof = $false
    updated_utc = [DateTime]::UtcNow.ToString("o")
}
$temp = "$coldPath.tmp-$([Guid]::NewGuid().ToString('N'))"
[IO.File]::WriteAllText($temp, (($proof | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $coldPath -Force

$state = if ($qualified) { "QUALIFIED" } else { "PARTIAL" }
Write-Host "BodyRig persistent storage authentication: $state"
Write-Host "Host:                 $($pre.host)"
Write-Host "Credential cycle:     $credentialGeneration"
Write-Host "Cold boots passed:    $($successfulBoots.Count)/$required"
Write-Host "Credential prompts:   0"
Write-Host "Real Stash decode:    PASS"
if (-not $qualified) {
    Write-Host "Next: reboot Windows once more and run this same command again."
}
