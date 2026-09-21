param(
    [Parameter(Mandatory = $true)][string]$CompositionAuthorityDir,
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][string]$M4PhotorealLinkDir,
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
    throw "Photoreal M5 link requires an exact clean BodyRig checkout."
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
$AcceptanceDir = Need-Directory -Path $AcceptanceDir -Label "canonical physical acceptance"
$M4PhotorealLinkDir = Need-Directory -Path $M4PhotorealLinkDir -Label "M4 Photoreal link authority"
$python = Resolve-WindowsPython -Requested $WindowsPython -RepoRoot $repoRoot

Write-Host "============================================================"
Write-Host "BODYRIG DIGITAL TWIN - PHOTOREAL M5 LINK"
Write-Host "Revision:            $head"
Write-Host "M4 composition:      $CompositionAuthorityDir"
Write-Host "Acceptance:          $AcceptanceDir"
Write-Host "M4 Photoreal link:   $M4PhotorealLinkDir"
Write-Host "M6 Photoreal:        PENDING LINK VALIDATION"
Write-Host "Production:          FALSE"
Write-Host "============================================================"

$arguments = @(
    "-m", "bodyrig.digital_twin_photoreal_m5_link_cli",
    "--composition-authority-dir", $CompositionAuthorityDir,
    "--acceptance-dir", $AcceptanceDir,
    "--m4-photoreal-link-dir", $M4PhotorealLinkDir,
    "--bodyrig-revision", $head
)
$output = @(& $python @arguments 2>&1)
$code = $LASTEXITCODE
foreach ($line in $output) {
    Write-Host ([string]$line)
}
if ($code -ne 0) {
    throw "Photoreal M5 link failed with exit code $code."
}

Write-Host ""
Write-Host "Photoreal M5 link:          PASS"
Write-Host "M6 Photoreal integration:   ELIGIBLE"
Write-Host "Production activation:      FALSE"
exit 0
