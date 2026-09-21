param(
    [Parameter(Mandatory = $true)][string]$CanonicalM6ReleaseDir,
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$PhotorealM5LinkDir,
    [Parameter(Mandatory = $true)][string]$M4PhotorealLinkDir,
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

function Resolve-WindowsPython {
    param([string]$Requested, [string]$RepoRoot)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) {
            throw "Windows Python not found: $Requested"
        }
        return (Resolve-Path -LiteralPath $Requested).Path
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
    throw "Photoreal M6 release requires an exact clean BodyRig checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') {
    throw "BodyRig HEAD is invalid."
}

$CanonicalM6ReleaseDir = Need-Directory -Path $CanonicalM6ReleaseDir -Label "canonical M6 release"
$CompositionAuthorityDir = Need-Directory -Path $CompositionAuthorityDir -Label "M4 composition authority"
$AcceptanceDir = Need-Directory -Path $AcceptanceDir -Label "canonical physical acceptance"
$PhotorealM5LinkDir = Need-Directory -Path $PhotorealM5LinkDir -Label "Photoreal M5 link"
$M4PhotorealLinkDir = Need-Directory -Path $M4PhotorealLinkDir -Label "M4 Photoreal link"
if (-not [string]::IsNullOrWhiteSpace($LibraryRoot)) {
    $LibraryRoot = Need-Directory -Path $LibraryRoot -Label "Person library"
}
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG DIGITAL TWIN - PHOTOREAL M6 RELEASE"
Write-Host "Revision:             $head"
Write-Host "Canonical M6:         $CanonicalM6ReleaseDir"
Write-Host "Photoreal M5:         $PhotorealM5LinkDir"
Write-Host "M4 Photoreal:         $M4PhotorealLinkDir"
Write-Host "Photoreal ready:      REQUIRES STRICT READBACK"
Write-Host "Production:           FINAL GATE ONLY"
Write-Host "============================================================"

$arguments = @(
    "-m", "bodyrig.digital_twin_photoreal_release_cli",
    "--canonical-m6-release-dir", $CanonicalM6ReleaseDir,
    "--composition-authority-dir", $CompositionAuthorityDir,
    "--acceptance-dir", $AcceptanceDir,
    "--photoreal-m5-link-dir", $PhotorealM5LinkDir,
    "--m4-photoreal-link-dir", $M4PhotorealLinkDir,
    "--bodyrig-revision", $head
)
if (-not [string]::IsNullOrWhiteSpace($LibraryRoot)) {
    $arguments += @("--library-root", $LibraryRoot)
}
$output = @(& $python @arguments 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Photoreal M6 release failed with exit code $code."
}

Write-Host ""
Write-Host "Photoreal M6 release:       PASS"
Write-Host "Photoreal digital twin:     READY"
Write-Host "Production activation:      TRUE"
exit 0
