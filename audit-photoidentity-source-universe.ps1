param(
    [Parameter(Mandatory = $true)][string]$PerformerId,
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [ValidateRange(1, 100000)][int]$MaximumScenes = 10000,
    [ValidateRange(1, 1000)][int]$PageSize = 250
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig photoidentity source-universe audit is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind source-universe audit to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Photoidentity source-universe audit requires an exact clean BodyRig checkout."
}

$storageStatus = Join-Path $repoRoot "storage-auth-status.ps1"
$pathMap = Join-Path $repoRoot "configure-stash-path-map.ps1"
foreach ($required in @($storageStatus, $pathMap)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required BodyRig operator is missing: $required" }
}
$storageRaw = @(& $storageStatus -PerformerId $PerformerId -Json 2>&1)
if ($LASTEXITCODE -ne 0 -or $storageRaw.Count -ne 1) {
    throw "Could not verify persistent storage qualification before source-universe audit."
}
try { $storage = ([string]$storageRaw[0]) | ConvertFrom-Json -Depth 20 }
catch { throw "Storage qualification status returned unreadable JSON." }
if ($storage.qualified -ne $true -or [int]$storage.cold_boots_passed -lt [int]$storage.cold_boots_required) {
    throw "Persistent storage authentication is not QUALIFIED; source-universe locality cannot be trusted yet. Next: $([string]$storage.next_command)"
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "BodyRig checkout Python is missing: $candidate" }
    $BodyRigPython = $candidate
}
$BodyRigPython = (Resolve-Path -LiteralPath $BodyRigPython).Path
$expectedModule = (Resolve-Path -LiteralPath (Join-Path $repoRoot "bodyrig\__init__.py")).Path
$actualRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualRaw.Count -ne 1) { throw "Could not verify checkout-bound BodyRig Python." }
$actualModule = [IO.Path]::GetFullPath(([string]$actualRaw[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$stashConfigPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
if (-not (Test-Path -LiteralPath $stashConfigPath -PathType Leaf)) { throw "Saved Stash config is missing: $stashConfigPath" }
try { $stash = Get-Content -LiteralPath $stashConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 10 }
catch { throw "Saved Stash config is unreadable JSON." }
if ([string]$stash.format -ne "bodyrig-local-stash-config" -or [int]$stash.version -ne 1) {
    throw "Saved Stash config has an unexpected format/version."
}
$stashUrl = ([string]$stash.url).Trim()
if ([string]::IsNullOrWhiteSpace($stashUrl) -or [string]::IsNullOrWhiteSpace([string]$stash.api_key_dpapi)) {
    throw "Saved Stash config lacks URL or protected API key."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\photoidentity-source-universe\$PerformerId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir, $repoRoot, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Source-universe evidence must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Source-universe output already exists: $OutputDir" }
New-Item -ItemType Directory -Path $OutputDir | Out-Null
$receipt = Join-Path $OutputDir "photoidentity-source-universe.json"

$secure = ConvertTo-SecureString ([string]$stash.api_key_dpapi)
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$apiKey = $null
$oldUrl = [Environment]::GetEnvironmentVariable("STASH_URL", "Process")
$oldKey = [Environment]::GetEnvironmentVariable("STASH_API_KEY", "Process")
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($apiKey)) { throw "Saved Stash API key could not be decrypted for this Windows user." }
    $env:STASH_URL = $stashUrl
    $env:STASH_API_KEY = $apiKey

    # Re-resolve the exact performer-scoped mappings now, after storage has
    # already been cold-boot qualified. This audit never trusts stale mappings.
    & $pathMap -PerformerId $PerformerId -ForceRefresh
    if ($LASTEXITCODE -ne 0) { throw "Stash path-map refresh failed before source-universe audit." }

    & $BodyRigPython -m bodyrig.photoidentity_source_universe `
        --performer-id $PerformerId `
        --stash-url $stashUrl `
        --api-key-env STASH_API_KEY `
        --maximum-scenes $MaximumScenes `
        --page-size $PageSize `
        --out $receipt
    if ($LASTEXITCODE -ne 0) { throw "Photoidentity source-universe audit failed with exit code $LASTEXITCODE." }
} finally {
    $apiKey = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    [Environment]::SetEnvironmentVariable("STASH_URL", $oldUrl, "Process")
    [Environment]::SetEnvironmentVariable("STASH_API_KEY", $oldKey, "Process")
}

if (-not (Test-Path -LiteralPath $receipt -PathType Leaf)) { throw "Source-universe audit did not publish its receipt." }
try { $result = Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Source-universe receipt is unreadable JSON." }
if ([string]$result.performer_id -ne [string]$PerformerId -or $result.stash_inventory_exhausted -ne $true) {
    throw "Source-universe receipt did not preserve performer/exhaustion authority."
}

Write-Host "BodyRig photoidentity source universe: PASS"
Write-Host "Revision:                $head"
Write-Host "Performer:               $PerformerId"
Write-Host "Stash scenes:            $([int]$result.stash_scene_count)"
Write-Host "Single-performer scenes: $([int]$result.single_performer_scene_count)"
Write-Host "Multi-performer scenes:  $([int]$result.multi_performer_scene_count)"
Write-Host "Safe local single files: $([int]$result.single_performer_projection_safe_local_video_count)"
Write-Host "Unresolved multi files:  $([int]$result.multi_performer_projection_safe_local_video_count)"
Write-Host "Inventory exhausted:     TRUE"
Write-Host "Biometric inference:     FALSE"
Write-Host "Generic guessing:        FALSE"
Write-Host "Render permitted:        FALSE"
Write-Host "Receipt:                 $receipt"
if ($result.multi_performer_identity_resolution_required -eq $true) {
    Write-Host "Next blocker: source-grounded track identity attestation is required before multi-performer media may enter the evidence pool."
}
