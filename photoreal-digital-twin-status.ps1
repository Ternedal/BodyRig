param(
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$PhotorealPersonBinding,
    [Parameter(Mandatory = $true)][string]$P3PhysicalReview,
    [string]$LibraryRoot = "",
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-WindowsPython {
    param([string]$Requested, [string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Need-File -Path $Requested -Label "Windows Python"
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Windows Python not found. Pass -WindowsPython explicitly."
    }
    return $command.Source
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$CompositionAuthorityDir = Need-Directory -Path $CompositionAuthorityDir -Label "M4 composition authority"
$AcceptanceDir = Need-Directory -Path $AcceptanceDir -Label "canonical physical acceptance"
$PhotorealPersonBinding = Need-File -Path $PhotorealPersonBinding -Label "Photoreal Person binding"
$P3PhysicalReview = Need-File -Path $P3PhysicalReview -Label "P3 physical runtime review"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

$arguments = @(
    "-m", "bodyrig.photoreal_digital_twin_operator_status_cli",
    "--composition-authority-dir", $CompositionAuthorityDir,
    "--acceptance-dir", $AcceptanceDir,
    "--photoreal-person-binding", $PhotorealPersonBinding,
    "--p3-physical-review", $P3PhysicalReview,
    "--operator-root", $repoRoot
)
if (-not [string]::IsNullOrWhiteSpace($LibraryRoot)) {
    $LibraryRoot = [IO.Path]::GetFullPath($LibraryRoot)
    $arguments += @("--library-root", $LibraryRoot)
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
