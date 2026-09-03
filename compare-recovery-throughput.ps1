param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

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
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig virtualenv Python not found: $python"
}

if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) {
    $dataRoot = [System.IO.Path]::GetFullPath($env:BODYRIG_DATA_DIR)
} elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $dataRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
} else {
    throw "BodyRig data root cannot be resolved from BODYRIG_DATA_DIR or LOCALAPPDATA."
}

$jobsRoot = Join-Path $dataRoot "ui-jobs"
$personRoot = Join-Path $dataRoot "people"
$baseline = Join-Path (Join-Path $jobsRoot $BaselineJobId) "job.json"
$candidate = Join-Path (Join-Path $jobsRoot $CandidateJobId) "job.json"
foreach ($item in @(
    @{ Path = $baseline; Label = "Baseline job" },
    @{ Path = $candidate; Label = "Candidate job" }
)) {
    if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
        throw "$($item.Label) not found: $($item.Path)"
    }
}

$args = @(
    "-m", "bodyrig.recovery_throughput_sampling_audit",
    $baseline,
    $candidate,
    "--person-root", $personRoot
)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("--out", [System.IO.Path]::GetFullPath($Out))
}

& $python @args
exit $LASTEXITCODE
