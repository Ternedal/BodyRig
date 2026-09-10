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
    throw "BodyRig multi-performer source discovery is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind multi-performer discovery to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Multi-performer source discovery requires an exact clean BodyRig checkout."
}

$storageStatus = Join-Path $repoRoot "storage-auth-status.ps1"
$pathMap = Join-Path $repoRoot "configure-stash-path-map.ps1"
foreach ($required in @($storageStatus, $pathMap)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required BodyRig operator is missing: $required" }
}
$storageRaw = @(& $storageStatus -PerformerId $PerformerId -Json 2>&1)
if ($LASTEXITCODE -ne 0 -or $storageRaw.Count -ne 1) {
    throw "Could not verify persistent storage qualification before multi-performer discovery."
}
try { $storage = ([string]$storageRaw[0]) | ConvertFrom-Json -Depth 20 }
catch { throw "Storage qualification status returned unreadable JSON." }
if ($storage.qualified -ne $true -or [int]$storage.cold_boots_passed -lt [int]$storage.cold_boots_required) {
    throw "Persistent storage authentication is not QUALIFIED; multi-performer source locality cannot be trusted yet. Next: $([string]$storage.next_command)"
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
    $OutputDir = Join-Path $env:LOCALAPPDATA "BodyRig\photoidentity-multiperformer\$PerformerId-$stamp-$suffix"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir, $repoRoot, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Multi-performer discovery output must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Multi-performer discovery output already exists: $OutputDir" }

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
    & $pathMap -PerformerId $PerformerId -ForceRefresh
    if ($LASTEXITCODE -ne 0) { throw "Stash path-map refresh failed before multi-performer discovery." }

    & $BodyRigPython -m bodyrig.photoidentity_multiperformer_source_discovery `
        --performer-id $PerformerId `
        --stash-url $stashUrl `
        --api-key-env STASH_API_KEY `
        --bodyrig-revision $head `
        --output-dir $OutputDir `
        --maximum-scenes $MaximumScenes `
        --page-size $PageSize
    if ($LASTEXITCODE -ne 0) { throw "Multi-performer source discovery failed with exit code $LASTEXITCODE." }
} finally {
    $apiKey = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    [Environment]::SetEnvironmentVariable("STASH_URL", $oldUrl, "Process")
    [Environment]::SetEnvironmentVariable("STASH_API_KEY", $oldKey, "Process")
}

$manifest = Join-Path $OutputDir "multiperformer-source-candidates.json"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Multi-performer discovery did not publish its public manifest." }
try { $result = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "Multi-performer discovery manifest is unreadable JSON." }
if ([string]$result.bodyrig_revision -ne $head -or [string]$result.performer_id -ne [string]$PerformerId -or $result.stash_inventory_exhausted -ne $true) {
    throw "Multi-performer discovery did not preserve revision/performer/exhaustion authority."
}

Write-Host ""
Write-Host "BodyRig multi-performer source discovery: PASS"
Write-Host "Revision:       $head"
Write-Host "Performer:      $PerformerId"
Write-Host "Candidates:     $([int]$result.candidate_count)"
Write-Host "Machine target: FALSE"
Write-Host "Biometric ID:   FALSE"
Write-Host "Reconstruction: FALSE"
Write-Host "Manifest:       $manifest"
foreach ($candidate in @($result.candidates)) {
    Write-Host ("  {0} | scene={1} | performers={2} | {3}x{4} | score={5}" -f `
        [string]$candidate.candidate_id, [string]$candidate.scene_id, [int]$candidate.performer_count, `
        [int]$candidate.width, [int]$candidate.height, [double]$candidate.review_priority_score)
}
if ([int]$result.candidate_count -gt 0) {
    Write-Host "Next: prepare one listed candidate with prepare-photoidentity-multiperformer-track-review.ps1; a human must choose the target track from source-derived review sheets."
}
