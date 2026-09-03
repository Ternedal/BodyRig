param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^person-[0-9a-f]{32}$')]
    [string]$PersonId,

    [string]$Out = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$compare = Join-Path $RepoRoot "compare-recovery-throughput.ps1"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig virtualenv Python not found: $python"
}
if (-not (Test-Path -LiteralPath $compare -PathType Leaf)) {
    throw "BodyRig recovery A/B comparator not found: $compare"
}

if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) {
    $dataRoot = [System.IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR)
} elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
} else {
    throw "BodyRig data root cannot be resolved from BODYRIG_DATA_DIR or LOCALAPPDATA."
}
$jobsRoot = Join-Path $dataRoot "ui-jobs"
if (-not (Test-Path -LiteralPath $jobsRoot -PathType Container)) {
    throw "BodyRig UI jobs root not found: $jobsRoot"
}

$samplingRevision = (& $python -c "from bodyrig.bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_REVISION; print(RECOVERY_TEMPORAL_SAMPLING_REVISION)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($samplingRevision)) {
    throw "Could not resolve BodyRig recovery sampling revision from the checked-out candidate."
}
$suffix = ";s:$samplingRevision"

$records = @()
foreach ($jobFile in @(Get-ChildItem -LiteralPath $jobsRoot -Directory -Filter "job-*" | ForEach-Object { Join-Path $_.FullName "job.json" })) {
    if (-not (Test-Path -LiteralPath $jobFile -PathType Leaf)) { continue }
    try {
        $job = Get-Content -LiteralPath $jobFile -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        continue
    }
    if ($job.format -ne "bodyrig-ui-job" -or $job.version -ne 1) { continue }
    if ($job.kind -ne "body-build" -or $job.status -ne "succeeded") { continue }
    if ($job.person_id -ne $PersonId) { continue }
    if ([string]::IsNullOrWhiteSpace([string]$job.completed_utc)) { continue }
    if ([string]::IsNullOrWhiteSpace([string]$job.clone_output)) { continue }

    $proofPath = Join-Path ([string]$job.clone_output) "clone\bodyrig-recovery-proof.json"
    if (-not (Test-Path -LiteralPath $proofPath -PathType Leaf)) { continue }
    try {
        $proof = Get-Content -LiteralPath $proofPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        continue
    }
    if ($proof.format -ne "bodyrig-recovery-proof" -or $proof.version -ne 1) { continue }
    $revision = [string]$proof.revision
    if ([string]::IsNullOrWhiteSpace($revision)) { continue }

    try {
        $completed = [DateTimeOffset]::Parse([string]$job.completed_utc)
    } catch {
        continue
    }

    $records += [pscustomobject]@{
        JobId = [string]$job.job_id
        Completed = $completed
        Revision = $revision
        IsCandidate = $revision.EndsWith($suffix, [StringComparison]::Ordinal)
    }
}

$candidate = @($records | Where-Object { $_.IsCandidate } | Sort-Object Completed -Descending | Select-Object -First 1)
if ($candidate.Count -ne 1) {
    throw "No succeeded sampled recovery candidate found for $PersonId."
}
$candidate = $candidate[0]
$expectedBaselineRevision = $candidate.Revision.Substring(0, $candidate.Revision.Length - $suffix.Length)
if ([string]::IsNullOrWhiteSpace($expectedBaselineRevision)) {
    throw "Latest sampled candidate has no valid uncapped parent recovery revision."
}

$baseline = @(
    $records |
        Where-Object { -not $_.IsCandidate -and $_.Revision -ceq $expectedBaselineRevision } |
        Sort-Object Completed -Descending |
        Select-Object -First 1
)
if ($baseline.Count -ne 1) {
    throw "No succeeded uncapped baseline with the exact parent recovery revision was found for $PersonId."
}
$baseline = $baseline[0]

Write-Host "BodyRig recovery A/B auto-discovery"
Write-Host "Person:    $PersonId"
Write-Host "Baseline:  $($baseline.JobId) | $($baseline.Revision)"
Write-Host "Candidate: $($candidate.JobId) | $($candidate.Revision)"
Write-Host "The exact source/selection/segment/recovery evidence is now revalidated by the fail-closed auditor."

$args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $compare,
    "-BaselineJobId", $baseline.JobId,
    "-CandidateJobId", $candidate.JobId,
    "-RepoRoot", $RepoRoot
)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("-Out", [System.IO.Path]::GetFullPath($Out))
}

& (Get-Command pwsh -ErrorAction Stop).Source @args
exit $LASTEXITCODE
