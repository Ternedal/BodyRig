param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^person-[0-9a-f]{32}$')]
    [string]$PersonId,

    [string]$RepoRoot = "",
    [switch]$NoWatch
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedBaselineRevision = "76c64a9546238663dedf750a1da4a230cc1e7fa4"
$BaseUrl = "http://127.0.0.1:8775"

function Get-Prop {
    param(
        $Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Default = $null
    )
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Invoke-BodyRigJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("Get", "Post")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Body = ""
    )
    $params = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        TimeoutSec = 15
    }
    if ($Method -eq "Post") {
        $params.ContentType = "application/json"
        $params.Body = $Body
    }
    try {
        return Invoke-RestMethod @params
    } catch {
        throw "BodyRig API call failed: $Method $Path | $($_.Exception.Message)"
    }
}

function Assert-RunningServiceAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Revision
    )
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable; cannot verify BodyRig service authority."
    }
    $statePath = Join-Path $env:LOCALAPPDATA "BodyRig\ui-service.json"
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "BodyRig service state is missing: $statePath"
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
    } catch {
        throw "BodyRig service state is unreadable: $statePath"
    }
    if ([string](Get-Prop $state "format" "") -cne "bodyrig-ui-service" -or [int](Get-Prop $state "version" 0) -ne 1) {
        throw "BodyRig service state format/version mismatch."
    }
    $stateRoot = [System.IO.Path]::GetFullPath([string](Get-Prop $state "root" ""))
    $stateRevision = [string](Get-Prop $state "revision" "")
    $statePid = [int](Get-Prop $state "pid" 0)
    if ($stateRoot -cne [System.IO.Path]::GetFullPath($Root)) {
        throw "Running BodyRig service is bound to a different checkout: $stateRoot"
    }
    if ($stateRevision -cne $Revision) {
        throw "Running BodyRig service revision mismatch. Expected $Revision, got $stateRevision."
    }
    if ($statePid -le 0 -or $null -eq (Get-Process -Id $statePid -ErrorAction SilentlyContinue)) {
        throw "BodyRig service state PID is not alive: $statePid"
    }
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Get-Location).Path
}
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not available."
}

$head = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig checkout revision."
}
if ($head -cne $ExpectedBaselineRevision) {
    throw "Baseline checkout mismatch. Expected $ExpectedBaselineRevision, got $head. Refusing to start A/B baseline."
}
$dirty = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read BodyRig checkout status."
}
if ($dirty.Count -gt 0) {
    throw "Baseline checkout is dirty. Refusing to start physical A/B baseline."
}

Assert-RunningServiceAuthority -Root $RepoRoot -Revision $ExpectedBaselineRevision

$health = Invoke-BodyRigJson -Method Get -Path "/api/v1/health"
if ((Get-Prop $health "ok" $false) -ne $true -or [string](Get-Prop $health "service" "") -cne "bodyrig") {
    throw "Port 8775 is not a healthy BodyRig service."
}
if ((Get-Prop $health "physical_build_ready" $false) -ne $true) {
    $reason = [string](Get-Prop $health "physical_build_reason" "unknown reason")
    throw "BodyRig physical build readiness is not green: $reason"
}

$stash = Invoke-BodyRigJson -Method Get -Path "/api/v1/stash/health"
if ((Get-Prop $stash "ok" $false) -ne $true -or (Get-Prop $stash "performer_read" $false) -ne $true) {
    throw "Stash health/performer-read is not green."
}

$person = Invoke-BodyRigJson -Method Get -Path "/api/v1/people/$PersonId"
$stashPerformer = Get-Prop $person "stash_performer" $null
$performerId = [string](Get-Prop $stashPerformer "id" "")
if ([string]::IsNullOrWhiteSpace($performerId)) {
    throw "Person $PersonId has no Stash performer binding."
}

$jobsResponse = Invoke-BodyRigJson -Method Get -Path "/api/v1/jobs?person_id=$PersonId"
$jobs = @(Get-Prop $jobsResponse "jobs" @())
$activeBodyJobs = @(
    $jobs | Where-Object {
        [string](Get-Prop $_ "kind" "") -eq "body-build" -and
        @("queued", "running") -contains [string](Get-Prop $_ "status" "")
    }
)
if ($activeBodyJobs.Count -gt 0) {
    $ids = @($activeBodyJobs | ForEach-Object { [string](Get-Prop $_ "job_id" "unknown") }) -join ", "
    throw "A body-build is already active for $PersonId: $ids"
}

$request = @{ feedback = ""; changes = @() } | ConvertTo-Json -Depth 4 -Compress
$job = Invoke-BodyRigJson -Method Post -Path "/api/v1/people/$PersonId/body/build" -Body $request
$jobId = [string](Get-Prop $job "job_id" "")
$jobRevision = [string](Get-Prop $job "bodyrig_revision" "")
if ($jobId -notmatch '^job-[0-9a-f]{32}$') {
    throw "BodyRig returned an invalid body-build job id."
}
if ($jobRevision -cne $ExpectedBaselineRevision) {
    throw "Started job is not bound to the exact baseline authority. Expected $ExpectedBaselineRevision, got $jobRevision."
}

Write-Host "BodyRig recovery throughput A/B baseline: STARTED"
Write-Host "Person:    $PersonId"
Write-Host "Performer: $performerId"
Write-Host "Job:       $jobId"
Write-Host "Revision:  $jobRevision"
Write-Host "Mode:      uncapped recovery baseline"

if ($NoWatch) {
    Write-Host "Monitor:   $RepoRoot\watch-body-build.ps1 -JobId $jobId"
    exit 0
}

$watch = Join-Path $RepoRoot "watch-body-build.ps1"
if (-not (Test-Path -LiteralPath $watch -PathType Leaf)) {
    throw "Canonical body-build monitor is missing from baseline checkout: $watch"
}
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
& $pwsh -NoProfile -ExecutionPolicy Bypass -File $watch -JobId $jobId -NoClear
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig body-build monitor failed with exit code $LASTEXITCODE."
}

$final = Invoke-BodyRigJson -Method Get -Path "/api/v1/jobs/$jobId"
$finalStatus = [string](Get-Prop $final "status" "")
if ($finalStatus -ne "succeeded") {
    $errorText = [string](Get-Prop $final "error" "")
    $tail = [string](Get-Prop $final "diagnostic_tail" "")
    Write-Host "BodyRig recovery throughput A/B baseline: FAILED"
    Write-Host "Job:      $jobId"
    Write-Host "Status:   $finalStatus"
    if (-not [string]::IsNullOrWhiteSpace($errorText)) { Write-Host "Error:    $errorText" }
    if (-not [string]::IsNullOrWhiteSpace($tail)) {
        Write-Host ""
        Write-Host "=== DIAGNOSTIC TAIL ==="
        Write-Host $tail
    }
    exit 1
}

Write-Host "BodyRig recovery throughput A/B baseline: SUCCEEDED"
Write-Host "Job:      $jobId"
Write-Host "Revision: $ExpectedBaselineRevision"
Write-Host "Next: record this job as the uncapped baseline before switching to the sampled candidate."
exit 0
