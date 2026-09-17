param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][ValidateSet("side-by-side", "over-under", "mono")][string]$StereoLayout,
    [Parameter(Mandatory = $true)][switch]$ConfirmVr180Equi,
    [string]$OutputPath = "",
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        throw "$Label is unreadable JSON: $Path"
    }
}

if (-not $ConfirmVr180Equi) {
    throw "Projection authority requires explicit -ConfirmVr180Equi operator attestation."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required on Windows."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$RunDirectory = Need-Directory -Path $RunDirectory -Label "Photoreal P0 run directory"
$planPath = Need-File -Path (Join-Path $RunDirectory "dataset-plan.json") -Label "Photoreal dataset plan"
$receiptPath = Need-File -Path (Join-Path $RunDirectory "source-receipt.json") -Label "Photoreal source receipt"
$plan = Read-Json -Path $planPath -Label "Photoreal dataset plan"

if ([string]$plan.format -ne "bodyrig-photoreal-dataset-plan" -or [int]$plan.version -ne 1) {
    throw "Photoreal dataset plan format/version mismatch."
}
$performerId = ([string]$plan.performer_id).Trim()
if ([string]::IsNullOrWhiteSpace($performerId)) {
    throw "Photoreal dataset plan performer id is missing."
}
if ([bool]$plan.production_activation) {
    throw "Photoreal dataset plan crossed production authority."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $BodyRigPython = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            throw "BodyRig Python was not found."
        }
        $BodyRigPython = $command.Source
    }
} else {
    $BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $authorityRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\projection-authority"
    [IO.Directory]::CreateDirectory($authorityRoot) | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = Join-Path $authorityRoot ("performer-{0}-{1}.json" -f $performerId, $stamp)
} else {
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $OutputPath
    if ([string]::IsNullOrWhiteSpace($parent)) {
        throw "Projection authority output path has no parent directory."
    }
    [IO.Directory]::CreateDirectory($parent) | Out-Null
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "Projection authority output already exists: $OutputPath"
}

$priorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($priorPythonPath)) {
        $repoRoot
    } else {
        "$repoRoot$([IO.Path]::PathSeparator)$priorPythonPath"
    })

    Write-Host "BODYRIG PHOTOREAL V2 - PREPARE PROJECTION AUTHORITY"
    Write-Host "Performer:       $performerId"
    Write-Host "Source run:      $RunDirectory"
    Write-Host "Stereo layout:   $StereoLayout"
    Write-Host "Geometry:        operator-verified VR180 equirectangular"
    Write-Host "Output:          $OutputPath"
    Write-Host "Production:      FALSE"
    Write-Host ""

    & $BodyRigPython -m bodyrig.photoreal_explicit_projection_authority_cli `
        --plan $planPath `
        --receipt $receiptPath `
        --out $OutputPath `
        --stereo-layout $StereoLayout `
        --operator-verified-vr180-equi
    $exitCode = $LASTEXITCODE
    if (-not $? -or $exitCode -ne 0) {
        throw "Projection authority preparation failed with exit code $exitCode."
    }
} finally {
    $env:PYTHONPATH = $priorPythonPath
}

$resolvedOutput = Need-File -Path $OutputPath -Label "Generated projection authority"
Write-Host ""
Write-Host "Projection authority: READY"
Write-Host "Use with: -ProjectionAuthority `"$resolvedOutput`""
