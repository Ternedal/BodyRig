param(
    [Parameter(Mandatory = $true)]
    [string]$RunRoot,

    [ValidateRange(1, 100)]
    [int]$TopMatches = 10,

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

$RunRoot = (Resolve-Path -LiteralPath $RunRoot).Path
if (-not (Test-Path -LiteralPath $RunRoot -PathType Container)) {
    throw "BodyRig Photoreal run root not found: $RunRoot"
}

$requiredArtifacts = @(
    "identity-bank.json",
    "identity-calibration-plan.json",
    "identity-calibration-extractor\output\negative-observations.json"
)

foreach ($relativePath in $requiredArtifacts) {
    $artifactPath = Join-Path $RunRoot $relativePath
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "Required Photoreal calibration artifact not found: $artifactPath"
    }
}

$arguments = @(
    "-m",
    "bodyrig.photoreal_identity_calibration_diagnostic_cli",
    "--run-root",
    $RunRoot,
    "--top-matches",
    [string]$TopMatches
)

if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $outputPath = [System.IO.Path]::GetFullPath($Out)
    $arguments += @("--out", $outputPath)
}

Write-Host "BodyRig Photoreal identity calibration diagnostic"
Write-Host "Run root: $RunRoot"
Write-Host "Authority: diagnostic-only"
Write-Host ""

& $python @arguments
exit $LASTEXITCODE
