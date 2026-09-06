param(
    [string]$SessionReport = "",
    [string]$AcceptanceDir = "",
    [ValidatePattern('^$|^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId = "",
    [string]$CompositionAuthorityDir = "",
    [string]$LibraryRoot = "",
    [string]$Serial = "",
    [string]$PerformerId = "",
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')][string]$BodyId = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the BodyRig operator status router."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$physicalStatus = Join-Path $repoRoot "physical-acceptance-status.ps1"
$highFidelityStatus = Join-Path $repoRoot "high-fidelity-physical-status.ps1"
$digitalTwinStatus = Join-Path $repoRoot "digital-twin-status.ps1"
$firstPhysicalRun = Join-Path $repoRoot "prepare-first-physical-run.ps1"
$profiledFirstPhysicalRun = Join-Path $repoRoot "prepare-profiled-first-physical-run.ps1"
foreach ($required in @($physicalStatus, $highFidelityStatus, $digitalTwinStatus, $firstPhysicalRun, $profiledFirstPhysicalRun)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Canonical BodyRig operator dependency is missing: $required"
    }
}

$hasSession = -not [string]::IsNullOrWhiteSpace($SessionReport)
$hasAcceptance = -not [string]::IsNullOrWhiteSpace($AcceptanceDir)
$hasPreview = -not [string]::IsNullOrWhiteSpace($PreviewJobId)
$hasComposition = -not [string]::IsNullOrWhiteSpace($CompositionAuthorityDir)
$hasLibrary = -not [string]::IsNullOrWhiteSpace($LibraryRoot)
$hasSerial = -not [string]::IsNullOrWhiteSpace($Serial)
$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)

function Invoke-CanonicalStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][hashtable]$Parameters
    )
    & $Script @Parameters
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    exit $code
}

if ($hasPerformer -xor $hasBodyId) {
    throw "Physical preflight requires -PerformerId and -BodyId together, or neither."
}
if ($hasPerformer -and $hasBodyId) {
    if ($hasSession -or $hasAcceptance -or $hasPreview -or $hasComposition -or $hasLibrary -or $hasSerial) {
        throw "Physical preflight mode cannot be combined with session, acceptance, high-fidelity, composition, library or serial arguments."
    }
    if ($Json) {
        throw "Physical preflight performer mode does not support -Json because the canonical rig/source doctor has human-readable output."
    }
    $parameters = @{
        PerformerId = $PerformerId
        BodyId = $BodyId
    }
    Invoke-CanonicalStatus -Script $profiledFirstPhysicalRun -Parameters $parameters
}

if ($hasComposition) {
    if (-not $hasAcceptance) {
        throw "-CompositionAuthorityDir requires -AcceptanceDir for the M4 -> M5 -> M6 digital-twin status chain."
    }
    if ($hasSession -or $hasPreview -or $hasSerial) {
        throw "Digital-twin mode cannot be combined with -SessionReport, -PreviewJobId or -Serial."
    }
    $parameters = @{
        CompositionAuthorityDir = $CompositionAuthorityDir
        AcceptanceDir = $AcceptanceDir
    }
    if ($hasLibrary) { $parameters.LibraryRoot = $LibraryRoot }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $digitalTwinStatus -Parameters $parameters
}

if ($hasPreview) {
    if ($hasSession -or $hasAcceptance -or $hasComposition -or $hasLibrary) {
        throw "High-fidelity preview mode cannot be combined with session, acceptance, composition or library arguments."
    }
    $parameters = @{ PreviewJobId = $PreviewJobId }
    if ($hasSerial) { $parameters.Serial = $Serial }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $highFidelityStatus -Parameters $parameters
}

if ($hasSession) {
    if ($hasAcceptance -or $hasComposition -or $hasPreview -or $hasLibrary -or $hasSerial) {
        throw "Physical session mode accepts only -SessionReport (plus -Json)."
    }
    $parameters = @{ SessionReport = $SessionReport }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $physicalStatus -Parameters $parameters
}

if ($hasAcceptance) {
    if ($hasComposition -or $hasPreview -or $hasLibrary -or $hasSerial) {
        throw "Physical acceptance mode accepts only -AcceptanceDir (plus -Json)."
    }
    $parameters = @{ AcceptanceDir = $AcceptanceDir }
    if ($Json) { $parameters.Json = $true }
    Invoke-CanonicalStatus -Script $physicalStatus -Parameters $parameters
}

if ($hasLibrary -or $hasSerial) {
    throw "-LibraryRoot and -Serial are stage-specific and require digital-twin or high-fidelity mode respectively."
}

$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1 -or ([string]$headLines[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve the current BodyRig Git checkout revision."
}
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify BodyRig checkout cleanliness."
}
$clean = $dirty.Count -eq 0
$nextCommand = if ($clean) { "& '" + $firstPhysicalRun.Replace("'", "''") + "'" } else { $null }
$message = if ($clean) {
    "No physical evidence selector was supplied. Start with the canonical read-only rig/source doctor before creating a physical session."
} else {
    "BodyRig checkout is dirty. Clean the checkout before starting the canonical physical preflight."
}
$result = [ordered]@{
    format = "bodyrig-operator-status-router"
    version = 1
    read_only = $true
    state = $(if ($clean) { "required" } else { "blocked" })
    stage = "physical-preflight"
    bodyrig_revision = $head
    checkout_clean = $clean
    next_gate = "physical-preflight"
    next_command = $nextCommand
    message = $message
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4 -Compress
} else {
    Write-Host "BodyRig operator status: $($result.state.ToUpperInvariant())"
    Write-Host "Stage:    $($result.stage)"
    Write-Host "Revision: $($result.bodyrig_revision) | clean=$($result.checkout_clean)"
    Write-Host $result.message
    if ($null -ne $result.next_command) {
        Write-Host "Next command:"
        Write-Host $result.next_command
    }
}

exit $(if ($clean) { 0 } else { 3 })
