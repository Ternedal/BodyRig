param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$BaselineBodyRigRevision,

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
    throw "Git is required to bind the review bundle to exact software authority."
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
$baselineBodyRigRevision = $BaselineBodyRigRevision.Trim().ToLowerInvariant()
if ($baselineBodyRigRevision -ceq $head) {
    throw "Baseline and candidate BodyRig revisions are identical; no software A/B exists."
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
Write-Host "Baseline software authority:  $baselineBodyRigRevision"
Write-Host "Candidate software authority: $head"
Write-Host "Output:    $Out"
Write-Host "Machine A/B must PASS before any review files are copied."

$moduleName = "bodyrig.recovery_throughput_review_bundle"
$expectedModule = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\recovery_throughput_review_bundle.py"))
$moduleArgs = @(
    $baselineRoot,
    $candidateRoot,
    "--expected-baseline-bodyrig-revision", $baselineBodyRigRevision,
    "--expected-candidate-bodyrig-revision", $head,
    "--person-root", $personRoot,
    "--out", $Out
)
$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$previousNoBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
$locationPushed = $false
$moduleExitCode = 1
try {
    Push-Location -LiteralPath $RepoRoot
    $locationPushed = $true
    $boundPythonPath = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$previousPythonPath" }
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $boundPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")

    $probeCode = "import importlib,pathlib,sys; m=importlib.import_module(sys.argv[1]); print(pathlib.Path(m.__file__).resolve())"
    $moduleRaw = @(& $python -c $probeCode $moduleName 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleRaw.Count -ne 1) {
        throw "Could not resolve checkout-bound recovery throughput review-bundle module."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery throughput review bundle imported BodyRig from a different checkout: $actualModule"
    }

    & $python -m $moduleName @moduleArgs
    $moduleExitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $previousNoBytecode, "Process")
    if ($locationPushed) { Pop-Location }
}
if ($moduleExitCode -ne 0) {
    exit $moduleExitCode
}

Write-Host "BodyRig recovery throughput review bundle: READY"
Write-Host "Open for human comparison: $(Join-Path $Out 'index.html')"
Write-Host "Authority: human review only; promotion/production remain false."
exit 0
