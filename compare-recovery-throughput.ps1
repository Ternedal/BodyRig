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
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to bind the A/B audit to the exact candidate checkout."
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}

$dirty = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read BodyRig Git status for A/B authority binding."
}
if ($dirty.Count -gt 0) {
    $dirty | ForEach-Object { Write-Host $_ }
    throw "BodyRig checkout has local changes; refusing recovery A/B audit against ambiguous candidate authority."
}
$candidateBodyRigRevision = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $candidateBodyRigRevision -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig candidate checkout revision."
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
    "--candidate-bodyrig-revision", $candidateBodyRigRevision,
    "--person-root", $personRoot
)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("--out", [System.IO.Path]::GetFullPath($Out))
}

& $python @args
exit $LASTEXITCODE
