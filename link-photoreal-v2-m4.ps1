param(
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$PhotorealPersonBinding,
    [Parameter(Mandatory = $true)][string]$P3PhysicalReview,
    [string]$LibraryRoot = "",
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
    throw "M4 Photoreal link requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$CompositionAuthorityDir = Need-Directory -Path $CompositionAuthorityDir -Label "M4 composition authority"
$PhotorealPersonBinding = Need-File -Path $PhotorealPersonBinding -Label "Photoreal Person binding"
$P3PhysicalReview = Need-File -Path $P3PhysicalReview -Label "P3 physical runtime review"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG DIGITAL TWIN - M4 PHOTOREAL LINK"
Write-Host "Revision:              $head"
Write-Host "M4 composition:        $CompositionAuthorityDir"
Write-Host "Photoreal binding:     $PhotorealPersonBinding"
Write-Host "P3 physical review:    $P3PhysicalReview"
Write-Host "M5 Photoreal eligible: PENDING VALIDATION"
Write-Host "Production:            FALSE"
Write-Host "============================================================"

$arguments = @(
    "-m", "bodyrig.digital_twin_photoreal_link_cli",
    "--composition-authority-dir", $CompositionAuthorityDir,
    "--photoreal-person-binding", $PhotorealPersonBinding,
    "--p3-physical-review", $P3PhysicalReview,
    "--bodyrig-revision", $head
)
if (-not [string]::IsNullOrWhiteSpace($LibraryRoot)) {
    $LibraryRoot = [IO.Path]::GetFullPath($LibraryRoot)
    $arguments += @("--library-root", $LibraryRoot)
}

$output = @(& $python @arguments 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "M4 Photoreal link failed with exit code $code."
}

Write-Host ""
Write-Host "M4 Photoreal link:           PASS"
Write-Host "M5 Photoreal integration:    ELIGIBLE"
Write-Host "Production activation:       FALSE"
exit 0
