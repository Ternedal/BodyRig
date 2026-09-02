param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$BaselineJobId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^job-[0-9a-f]{32}$')]
    [string]$CandidateJobId,

    [string]$DataDir = "",
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "BodyRig venv Python is missing: $python"
}

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    if (-not [string]::IsNullOrWhiteSpace($env:BODYRIG_DATA_DIR)) {
        $DataDir = Join-Path $env:BODYRIG_DATA_DIR "ui-jobs"
    } elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $DataDir = Join-Path $env:LOCALAPPDATA "BodyRig\ui-jobs"
    } else {
        throw "BodyRig data root is unavailable; pass -DataDir explicitly."
    }
}
$DataDir = [System.IO.Path]::GetFullPath($DataDir)
if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) {
    throw "BodyRig UI job directory is missing: $DataDir"
}
$dataRoot = Split-Path -Parent $DataDir
$personRoot = Join-Path $dataRoot "people"
if (-not (Test-Path -LiteralPath $personRoot -PathType Container)) {
    throw "BodyRig Person Library is missing beside the UI job root: $personRoot"
}

$baseline = Join-Path (Join-Path $DataDir $BaselineJobId) "job.json"
$candidate = Join-Path (Join-Path $DataDir $CandidateJobId) "job.json"
foreach ($entry in @(
    @{ Label = "Baseline"; Path = $baseline },
    @{ Label = "Candidate"; Path = $candidate }
)) {
    if (-not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) {
        throw "$($entry.Label) BodyRig job is missing: $($entry.Path)"
    }
}

$argsList = @(
    "-m", "bodyrig.recovery_throughput_sampling_audit",
    $baseline,
    $candidate,
    "--person-root", $personRoot
)
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $outPath = [System.IO.Path]::GetFullPath($Out)
    $argsList += @("--out", $outPath)
}

Write-Host "BodyRig recovery throughput sampling A/B audit"
Write-Host "Baseline:  $BaselineJobId"
Write-Host "Candidate: $CandidateJobId"
Write-Host "Data root: $dataRoot"
Write-Host "Authority: read-only machine evidence; human visual review remains mandatory"
Write-Host ""

& $python @argsList
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ""
    Write-Host "BodyRig recovery throughput sampling A/B audit: BLOCKED"
    exit $code
}

Write-Host ""
Write-Host "BodyRig recovery throughput sampling A/B audit: MACHINE PASS"
Write-Host "Candidate is eligible for human A/B fidelity review only; no promotion authority was granted."
exit 0
