param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$PriorAuthority,
    [Parameter(Mandatory = $true)][ValidateSet("side-by-side","over-under","mono")][string]$NewStereoLayout,
    [switch]$ConfirmNewVr180Equi,
    [string]$OutputPath = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

if (-not $ConfirmNewVr180Equi) {
    throw "Projection authority extension requires explicit -ConfirmNewVr180Equi attestation for only the newly spatial sources."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required on Windows." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$RunDirectory = Need-Directory $RunDirectory "Photoreal metadata run"
$PriorAuthority = Need-File $PriorAuthority "Prior projection authority"
$plan = Need-File (Join-Path $RunDirectory "dataset-plan.json") "Photoreal dataset plan"
$receipt = Need-File (Join-Path $RunDirectory "source-receipt.json") "Photoreal source receipt"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = (Resolve-Path -LiteralPath $candidate).Path }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "BodyRig Python was not found." }
        $BodyRigPython = $command.Source
    }
} else {
    $BodyRigPython = Need-File $BodyRigPython "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $root = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\projection-authority"
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = Join-Path $root ("performer-42-{0}-extended.json" -f $stamp)
} else {
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    [IO.Directory]::CreateDirectory((Split-Path -Parent $OutputPath)) | Out-Null
}
if (Test-Path -LiteralPath $OutputPath) { throw "Projection authority output already exists: $OutputPath" }

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath" })
    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - EXTEND PROJECTION AUTHORITY"
    Write-Host "Run:              $RunDirectory"
    Write-Host "Prior authority:  $PriorAuthority"
    Write-Host "New-source layout:$NewStereoLayout"
    Write-Host "Scope:            NEW SPATIAL SOURCES ONLY"
    Write-Host "Production:       FALSE"
    Write-Host "============================================================"

    $args = @(
        "-m","bodyrig.photoreal_projection_authority_extend_cli",
        "--plan",$plan,
        "--receipt",$receipt,
        "--prior-authority",$PriorAuthority,
        "--out",$OutputPath,
        "--new-stereo-layout",$NewStereoLayout,
        "--operator-verified-new-vr180-equi"
    )
    & $BodyRigPython @args
    if ($LASTEXITCODE -ne 0) { throw "Projection authority extension failed with exit code $LASTEXITCODE." }
} finally {
    $env:PYTHONPATH = $priorPythonPath
}

$resolved = Need-File $OutputPath "Extended projection authority"
Write-Host ""
Write-Host "Projection authority extension: READY"
Write-Host "Use with: -ProjectionAuthority `"$resolved`""
Write-Host "Production: FALSE"
