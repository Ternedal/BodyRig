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
$baselineBodyRigRevision = $BaselineBodyRigRevision.Trim().ToLowerInvariant()
if ($baselineBodyRigRevision -ceq $candidateBodyRigRevision) {
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
    $baseline,
    $candidate,
    "--baseline-bodyrig-revision", $baselineBodyRigRevision,
    "--candidate-bodyrig-revision", $candidateBodyRigRevision,
    "--person-root", $personRoot
)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $args += @("--out", [System.IO.Path]::GetFullPath($Out))
}

$moduleName = "bodyrig.recovery_throughput_sampling_audit"
$expectedModule = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\recovery_throughput_sampling_audit.py"))
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
        throw "Could not resolve checkout-bound recovery throughput audit module."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleRaw[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery throughput audit imported BodyRig from a different checkout: $actualModule"
    }

    & $python -m $moduleName @args
    $moduleExitCode = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $previousNoBytecode, "Process")
    if ($locationPushed) { Pop-Location }
}
exit $moduleExitCode
