param(
    [Parameter(Mandatory = $true)][string]$PersonLibrary,
    [Parameter(Mandatory = $true)][string]$PersonId,
    [Parameter(Mandatory = $true)][string]$AssemblyReceipt,
    [Parameter(Mandatory = $true)][string]$BodyReleaseStatus,
    [Parameter(Mandatory = $true)][string]$P3PhysicalReview,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$WindowsPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
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
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Photoreal Person binding requires an exact clean BodyRig checkout."
}

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$PersonLibrary = Need-Directory -Path $PersonLibrary -Label "Person library"
$AssemblyReceipt = Need-File -Path $AssemblyReceipt -Label "Person assembly receipt"
$BodyReleaseStatus = Need-File -Path $BodyReleaseStatus -Label "body release status"
$P3PhysicalReview = Need-File -Path $P3PhysicalReview -Label "P3 physical runtime review"
$Output = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $Output) {
    throw "Photoreal Person binding output already exists: $Output"
}

$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - PERSON BINDING"
Write-Host "Revision:            $head"
Write-Host "Person:              $PersonId"
Write-Host "Assembly:            $AssemblyReceipt"
Write-Host "Body release:        $BodyReleaseStatus"
Write-Host "P3 physical review:  $P3PhysicalReview"
Write-Host "Output:              $Output"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

$arguments = @(
    "-m", "bodyrig.photoreal_person_binding_cli",
    "--person-library", $PersonLibrary,
    "--person-id", $PersonId,
    "--assembly-receipt", $AssemblyReceipt,
    "--body-release-status", $BodyReleaseStatus,
    "--p3-physical-review", $P3PhysicalReview,
    "--bodyrig-revision", $head,
    "--out", $Output
)

$outputLines = @(& $python @arguments 2>&1)
$code = $LASTEXITCODE
foreach ($line in $outputLines) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Photoreal Person binding failed with exit code $code."
}

if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) {
    throw "Photoreal Person binding did not create its authority file."
}

$authority = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ($authority.photoreal_binding_authority -isnot [bool] -or $authority.photoreal_binding_authority -ne $true) {
    throw "Photoreal Person binding did not grant binding authority."
}
if ($authority.m4_photoreal_integration_eligible -isnot [bool] -or $authority.m4_photoreal_integration_eligible -ne $true) {
    throw "Photoreal Person binding is not eligible for M4 integration."
}
if ($authority.production_activation -isnot [bool] -or $authority.production_activation -ne $false) {
    throw "Photoreal Person binding crossed production authority."
}

Write-Host ""
Write-Host "Photoreal Person binding: PASS"
Write-Host "Binding id:                 $($authority.binding_id)"
Write-Host "Stash performer:            $($authority.stash_performer_id)"
Write-Host "M4 integration eligibility: TRUE"
Write-Host "Production activation:      FALSE"
exit 0
