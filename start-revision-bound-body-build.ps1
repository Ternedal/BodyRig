param(
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",

    [string]$PerformerId = "",

    [switch]$RetainPrivateWorkspaceForAb,

    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')]
    [string]$BaseUri = "http://127.0.0.1:8775"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for revision-bound BodyRig body builds."
}
if ([string]::IsNullOrWhiteSpace($PersonId) -eq [string]::IsNullOrWhiteSpace($PerformerId)) {
    throw "Pass exactly one of -PersonId or -PerformerId."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not resolve exact BodyRig checkout revision."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify BodyRig checkout cleanliness."
}
if ($dirty.Count -gt 0) {
    $dirty | ForEach-Object { Write-Host $_ }
    throw "BodyRig checkout is dirty. Revision-bound body builds require exact clean authority."
}

try {
    $health = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/health" -TimeoutSec 2
} catch {
    throw "BodyRig local service is not ready at $BaseUri. Start/restart it from this exact checkout before a physical body build."
}
if ($health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
    throw "The configured endpoint did not identify a healthy BodyRig service."
}

try {
    $authority = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 2
} catch {
    throw "BodyRig service does not expose exact operator checkout authority. Update/restart it from this checkout before a physical body build."
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

if ([string]::IsNullOrWhiteSpace($PersonId)) {
    try {
        $people = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/people" -TimeoutSec 10
    } catch {
        throw "Could not resolve BodyRig Person for Stash performer $PerformerId."
    }
    $matches = @($people.people | Where-Object {
        $null -ne $_.source -and
        [string]$_.source.kind -eq "stash-performer" -and
        [string]$_.source.performer_id -eq $PerformerId
    })
    if ($matches.Count -eq 0) {
        throw "No BodyRig Person is bound to Stash performer $PerformerId."
    }
    if ($matches.Count -gt 1) {
        throw "Multiple BodyRig Persons are bound to Stash performer $PerformerId. Pass -PersonId explicitly."
    }
    $PersonId = [string]$matches[0].person_id
    if ($PersonId -notmatch '^person-[0-9a-f]{32}$') {
        throw "Resolved BodyRig Person id is not canonical: $PersonId"
    }
}

try {
    $jobs = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/jobs?person_id=$([uri]::EscapeDataString($PersonId))" -TimeoutSec 10
} catch {
    throw "Could not inspect existing BodyRig jobs for $PersonId."
}
$active = @($jobs.jobs | Where-Object {
    [string]$_.kind -eq "body-build" -and [string]$_.status -in @("queued", "running")
})
if ($active.Count -gt 0) {
    throw "A body-build is already active for ${PersonId}: $([string]$active[0].job_id)"
}

$payload = @{
    expected_bodyrig_revision = $head
    retain_private_workspace_for_ab = [bool]$RetainPrivateWorkspaceForAb
} | ConvertTo-Json -Depth 4 -Compress

try {
    $started = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUri/api/v1/people/$PersonId/body/build-revision-bound" `
        -ContentType "application/json" `
        -Body $payload `
        -TimeoutSec 15
} catch {
    throw "BodyRig service refused revision-bound body build for ${PersonId}: $($_.Exception.Message)"
}

$jobId = [string]$started.job_id
$jobRevision = ([string]$started.bodyrig_revision).Trim().ToLowerInvariant()
if ($jobId -notmatch '^job-[0-9a-f]{32}$') {
    throw "BodyRig body-build enqueue did not return a canonical job id."
}
if ([string]$started.kind -ne "body-build" -or [string]$started.person_id -ne $PersonId) {
    throw "BodyRig body-build enqueue returned unexpected job identity."
}
if ($jobRevision -ne $head) {
    throw "BodyRig body-build enqueue revision differs from the bound checkout: job=$jobRevision, checkout=$head"
}
if ($RetainPrivateWorkspaceForAb) {
    $retention = $started.ab_baseline_retention
    if ($null -eq $retention -or [string]$retention.format -ne "bodyrig-ab-baseline-retention" -or [int]$retention.version -ne 1 -or
        $retention.retain_private_workspace -ne $true -or ([string]$retention.expected_bodyrig_revision).ToLowerInvariant() -ne $head -or
        [string]$retention.job_id -ne $jobId) {
        throw "BodyRig did not persist exact A/B baseline retention authority on the queued job."
    }
}

Write-Host "BodyRig revision-bound body build: STARTED"
Write-Host "Person:   $PersonId"
Write-Host "Revision: $head"
Write-Host "Job:      $jobId"
Write-Host "A/B retained workspace: $([bool]$RetainPrivateWorkspaceForAb)"
Write-Host "Monitor:  .\watch-body-build.ps1 -JobId '$jobId'"

[pscustomobject]@{
    job_id = $jobId
    person_id = $PersonId
    bodyrig_revision = $head
    status = [string]$started.status
    ab_baseline_retention = $(if ($RetainPrivateWorkspaceForAb) { $started.ab_baseline_retention } else { $null })
} | ConvertTo-Json -Depth 8 -Compress
