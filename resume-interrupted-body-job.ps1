param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$JobId,
    [switch]$AssessOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for BodyRig interrupted body recovery."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve exact BodyRig checkout revision."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) {
    throw "BodyRig checkout is dirty. Interrupted body recovery requires exact clean authority."
}

$baseUri = "http://127.0.0.1:8775"
try {
    $health = Invoke-RestMethod -Method Get -Uri "$baseUri/api/v1/health" -TimeoutSec 2
} catch {
    throw "BodyRig local service is not ready on 127.0.0.1:8775. Start it from this checkout before interrupted recovery."
}
if ($health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
    throw "Port 8775 did not identify a healthy BodyRig service."
}

try {
    $authority = Invoke-RestMethod -Method Get -Uri "$baseUri/api/v1/operator-authority" -TimeoutSec 2
} catch {
    throw "BodyRig service does not expose exact operator checkout authority. Update/restart it from this checkout before interrupted recovery."
}
$serviceRevision = ([string]$authority.bodyrig_revision).Trim().ToLowerInvariant()
if ($authority.ok -ne $true) {
    throw "Running BodyRig service is not ready for physical work: $([string]$authority.reason)"
}
if ($serviceRevision -notmatch '^[0-9a-f]{40}$') {
    throw "Running BodyRig service did not return a canonical bodyrig_revision."
}
if ($serviceRevision -ne $head) {
    throw "Running BodyRig service revision differs from the operator checkout: service=$serviceRevision, checkout=$head"
}

$statusUri = "$baseUri/api/v1/jobs/$JobId/resume-status"
try {
    $status = Invoke-RestMethod -Method Get -Uri $statusUri -TimeoutSec 10
} catch {
    throw "Could not inspect interrupted recovery status for $JobId."
}
if ($status.available -ne $true) {
    throw "Interrupted recovery is not available for ${JobId}: $([string]$status.reason)"
}
if ([string]$status.bodyrig_revision -ne $head) {
    throw "Interrupted recovery is bound to another BodyRig revision: $([string]$status.bodyrig_revision); checkout=$head"
}
if ($status.expensive_reconstruction_rerun -ne $false) {
    throw "Interrupted recovery unexpectedly requires expensive reconstruction; refusing optimized resume path."
}

if ($AssessOnly) {
    $status | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

$resumeUri = "$baseUri/api/v1/jobs/$JobId/resume"
try {
    $started = Invoke-RestMethod -Method Post -Uri $resumeUri -TimeoutSec 15
} catch {
    throw "BodyRig service refused interrupted recovery for ${JobId}: $($_.Exception.Message)"
}
if ([string]::IsNullOrWhiteSpace([string]$started.job_id)) {
    throw "BodyRig interrupted recovery started without returning a new job id."
}
if (([string]$started.bodyrig_revision).Trim().ToLowerInvariant() -ne $head) {
    throw "Interrupted recovery enqueue returned a different BodyRig revision than the bound checkout."
}

Write-Host "BodyRig interrupted body recovery: STARTED"
Write-Host "Source job: $JobId"
Write-Host "Recovery mode: $([string]$status.recovery_mode)"
Write-Host "Expensive reconstruction rerun: false"
Write-Host "Fitter rerun: $([bool]$status.fitter_rerun)"
Write-Host "BodyRig revision: $head"
Write-Host "New job: $([string]$started.job_id)"
Write-Host "Monitor the BodyRig UI/job status; do not start a competing body build for the same person."
exit 0
