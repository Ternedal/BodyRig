param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^person-[0-9a-f]{32}$')]
    [string]$PersonId,

    [string]$Out = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-JsonPropertyValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

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

$samplingOutput = @(& $python -c "from bodyrig.bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_REVISION; print(RECOVERY_TEMPORAL_SAMPLING_REVISION)")
if ($LASTEXITCODE -ne 0 -or $samplingOutput.Count -eq 0) {
    throw "Could not resolve BodyRig recovery sampling revision from the checked-out candidate."
}
$samplingRevision = ([string]$samplingOutput[-1]).Trim()
if ([string]::IsNullOrWhiteSpace($samplingRevision)) {
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

    $format = Get-JsonPropertyValue -Object $job -Name "format"
    $version = Get-JsonPropertyValue -Object $job -Name "version"
    $kind = Get-JsonPropertyValue -Object $job -Name "kind"
    $status = Get-JsonPropertyValue -Object $job -Name "status"
    $personIdValue = [string](Get-JsonPropertyValue -Object $job -Name "person_id")
    $completedUtc = [string](Get-JsonPropertyValue -Object $job -Name "completed_utc")
    $cloneOutput = [string](Get-JsonPropertyValue -Object $job -Name "clone_output")
    $jobId = [string](Get-JsonPropertyValue -Object $job -Name "job_id")

    if ($format -ne "bodyrig-ui-job" -or $version -ne 1) { continue }
    if ($kind -ne "body-build" -or $status -ne "succeeded") { continue }
    if ($personIdValue -ne $PersonId) { continue }
    if ($jobId -notmatch '^job-[0-9a-f]{32}$') { continue }
    if ([string]::IsNullOrWhiteSpace($completedUtc)) { continue }
    if ([string]::IsNullOrWhiteSpace($cloneOutput)) { continue }

    $proofPath = Join-Path $cloneOutput "clone\bodyrig-recovery-proof.json"
    if (-not (Test-Path -LiteralPath $proofPath -PathType Leaf)) { continue }
    try {
        $proof = Get-Content -LiteralPath $proofPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        continue
    }

    $proofFormat = Get-JsonPropertyValue -Object $proof -Name "format"
    $proofVersion = Get-JsonPropertyValue -Object $proof -Name "version"
    $revision = [string](Get-JsonPropertyValue -Object $proof -Name "revision")
    if ($proofFormat -ne "bodyrig-recovery-proof" -or $proofVersion -ne 1) { continue }
    if ([string]::IsNullOrWhiteSpace($revision)) { continue }

    try {
        $completed = [DateTimeOffset]::Parse($completedUtc)
    } catch {
        continue
    }

    $records += [pscustomobject]@{
        JobId = $jobId
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
