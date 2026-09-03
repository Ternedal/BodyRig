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
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot is not a BodyRig Git checkout: $RepoRoot"
}

$head = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact candidate checkout revision."
}
$dirty = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read candidate checkout status."
}
if ($dirty.Count -gt 0) {
    throw "Candidate checkout is dirty. Refusing to build a human A/B review bundle."
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
$baselineRoot = Join-Path $jobsRoot $BaselineJobId
$candidateRoot = Join-Path $jobsRoot $CandidateJobId
if (-not (Test-Path -LiteralPath (Join-Path $baselineRoot "job.json") -PathType Leaf)) {
    throw "Baseline body-build job not found: $BaselineJobId"
}
if (-not (Test-Path -LiteralPath (Join-Path $candidateRoot "job.json") -PathType Leaf)) {
    throw "Candidate body-build job not found: $CandidateJobId"
}

if ([string]::IsNullOrWhiteSpace($Out)) {
    $reviewRoot = Join-Path $dataRoot "recovery-throughput-reviews"
    $Out = Join-Path $reviewRoot "$BaselineJobId--$CandidateJobId"
}
$Out = [System.IO.Path]::GetFullPath($Out)

Write-Host "BodyRig recovery throughput human A/B review bundle"
Write-Host "Baseline:  $BaselineJobId"
Write-Host "Candidate: $CandidateJobId"
Write-Host "Candidate software authority: $head"
Write-Host "Output:    $Out"
Write-Host "Machine A/B must PASS before any review files are copied."

& $python -m bodyrig.recovery_throughput_review_bundle `
    $baselineRoot `
    $candidateRoot `
    --expected-candidate-bodyrig-revision $head `
    --person-root $personRoot `
    --out $Out
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "BodyRig recovery throughput review bundle: READY"
Write-Host "Open for human comparison: $(Join-Path $Out 'index.html')"
Write-Host "Authority: human review only; promotion/production remain false."
exit 0
