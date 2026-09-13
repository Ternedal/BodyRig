param(
    [Parameter(Mandatory = $true)][ValidatePattern('^person-[0-9a-f]{32}$')][string]$PersonId,
    [Parameter(Mandatory = $true)][ValidatePattern('^job-[0-9a-f]{32}$')][string]$BodyJobId,
    [Parameter(Mandatory = $true)][ValidateSet('female','male','neutral')][string]$TargetFamily,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Revision,
    [ValidatePattern('^https?://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$')][string]$BaseUri = 'http://127.0.0.1:8775',
    [ValidateRange(1, 60)][int]$PollSeconds = 5,
    [ValidateRange(60, 21600)][int]$TimeoutSeconds = 7200
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7+ (pwsh) is required for high-fidelity preview continuation.'
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$updateScript = Join-Path $repoRoot 'update-windows.ps1'
if (-not (Test-Path -LiteralPath $updateScript -PathType Leaf)) {
    throw 'Current BodyRig checkout does not expose update-windows.ps1.'
}

$initialHeadLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $initialHeadLines.Count -ne 1) {
    throw 'Could not resolve current BodyRig Git revision before historical re-entry.'
}
$initialHead = ([string]$initialHeadLines[0]).Trim().ToLowerInvariant()
if ($initialHead -notmatch '^[0-9a-f]{40}$') {
    throw 'Current BodyRig Git revision is not canonical before historical re-entry.'
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw 'Could not verify BodyRig checkout cleanliness before historical re-entry.'
}
if ($dirty.Count -gt 0) {
    $dirty | ForEach-Object { Write-Host $_ }
    throw 'BodyRig checkout is dirty. High-fidelity preview continuation requires exact clean authority.'
}

Write-Host 'BodyRig high-fidelity preview continuation'
Write-Host "Person:        $PersonId"
Write-Host "Body job:      $BodyJobId"
Write-Host "Target family: $TargetFamily"
Write-Host "Revision:      $Revision"
Write-Host 'Reconstruction rerun: FALSE'
Write-Host ''

# Run the updater from the current qualified checkout. It owns safe historical
# re-entry, environment refresh and local-service restart. The caller script is
# already parsed in memory, so it can continue after the checkout becomes
# detached on the exact historical producer revision.
& $updateScript -Revision $Revision -NoBrowser
if (-not $?) {
    throw "Historical BodyRig re-entry failed for revision $Revision."
}

$actualHeadLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualHeadLines.Count -ne 1) {
    throw 'Could not resolve BodyRig Git revision after historical re-entry.'
}
$actualHead = ([string]$actualHeadLines[0]).Trim().ToLowerInvariant()
if ($actualHead -ne $Revision) {
    throw "Historical re-entry ended on the wrong revision: expected $Revision, got $actualHead."
}
$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0) {
    throw 'Historical BodyRig checkout is not clean after re-entry.'
}

try {
    $health = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/health" -TimeoutSec 3
} catch {
    throw "BodyRig local service is not ready at $BaseUri after historical re-entry."
}
if ($health.ok -ne $true -or [string]$health.service -ne 'bodyrig') {
    throw 'The configured endpoint did not identify a healthy BodyRig service after historical re-entry.'
}

try {
    $authority = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/operator-authority" -TimeoutSec 3
} catch {
    throw 'BodyRig service does not expose exact operator checkout authority after historical re-entry.'
}
$serviceRevision = ([string]$authority.bodyrig_revision).Trim().ToLowerInvariant()
if ($authority.ok -ne $true -or $serviceRevision -ne $Revision) {
    throw "BodyRig service authority does not match the historical producer revision: service=$serviceRevision expected=$Revision reason=$([string]$authority.reason)"
}

$payload = @{
    body_job_id = $BodyJobId
    target_family = $TargetFamily
} | ConvertTo-Json -Depth 4 -Compress

try {
    $preview = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUri/api/v1/people/$PersonId/body/high-fidelity-preview" `
        -ContentType 'application/json' `
        -Body $payload `
        -TimeoutSec 30
} catch {
    throw "BodyRig refused high-fidelity preview continuation for ${PersonId}/${BodyJobId}: $($_.Exception.Message)"
}

$previewJobId = [string]$preview.job_id
if ($previewJobId -notmatch '^hfpreview-[0-9a-f]{32}$') {
    throw 'High-fidelity preview enqueue did not return a canonical preview job id.'
}
if ([string]$preview.person_id -ne $PersonId -or [string]$preview.body_job_id -ne $BodyJobId) {
    throw 'High-fidelity preview enqueue returned different Person/body-job authority.'
}
if (([string]$preview.bodyrig_revision).Trim().ToLowerInvariant() -ne $Revision) {
    throw 'High-fidelity preview enqueue returned a different BodyRig revision.'
}
if ([string]$preview.target_family -ne $TargetFamily) {
    throw 'High-fidelity preview enqueue returned a different target family.'
}

Write-Host "Preview:       $previewJobId"
Write-Host "Initial state: $([string]$preview.status)/$([string]$preview.stage)"

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$current = $preview
while ([string]$current.status -notin @('succeeded','failed','interrupted')) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw "High-fidelity preview did not reach a terminal state within the configured timeout; preview=$previewJobId."
    }
    Start-Sleep -Seconds $PollSeconds
    try {
        $current = Invoke-RestMethod -Method Get -Uri "$BaseUri/api/v1/high-fidelity-preview-jobs/$previewJobId" -TimeoutSec 15
    } catch {
        throw "Could not read high-fidelity preview status for ${previewJobId}: $($_.Exception.Message)"
    }
    if ([string]$current.job_id -ne $previewJobId -or [string]$current.person_id -ne $PersonId -or [string]$current.body_job_id -ne $BodyJobId) {
        throw 'High-fidelity preview status crossed its exact Person/body-job authority.'
    }
    if (([string]$current.bodyrig_revision).Trim().ToLowerInvariant() -ne $Revision) {
        throw 'High-fidelity preview status crossed its exact BodyRig revision authority.'
    }
    Write-Host "Preview state: $([string]$current.status)/$([string]$current.stage) | $([int]$current.progress)%"
}

if ([string]$current.status -ne 'succeeded') {
    $reason = [string]$current.error
    if ([string]::IsNullOrWhiteSpace($reason)) { $reason = [string]$current.message }
    throw "High-fidelity preview stopped $([string]$current.status): $reason"
}

$statusScript = Join-Path $repoRoot 'high-fidelity-physical-status.ps1'
if (-not (Test-Path -LiteralPath $statusScript -PathType Leaf)) {
    throw 'Historical producer revision does not expose high-fidelity-physical-status.ps1.'
}

Write-Host ''
Write-Host 'BodyRig high-fidelity preview: SUCCEEDED'
Write-Host "Preview:  $previewJobId"
Write-Host "Revision: $Revision"
Write-Host 'Checkout remains frozen on the historical producer revision for continuation.'
Write-Host ''

& $statusScript -PreviewJobId $previewJobId
exit $LASTEXITCODE
