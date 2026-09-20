param(
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [Parameter(Mandatory = $true)][string[]]$AcceptGroup,
    [Parameter(Mandatory = $true)][string[]]$RejectGroup,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmIdentity,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Convert-ToWslPath {
    param([string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) { return $WindowsPath }

    $pythonCode = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $encoded = ([string]$lines[0]).Trim()
    try {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    } catch {
        throw "BodyRig WSL bridge returned invalid encoded path data: $WindowsPath"
    }
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL bridge returned invalid path: $WindowsPath"
    }
    return $value
}

if (-not $ConfirmIdentity.IsPresent) {
    throw "Human identity-group attestation requires explicit -ConfirmIdentity."
}
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim().Length -lt 10) {
    throw "QualityNote must contain at least 10 non-whitespace characters."
}
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"

$dirty = @(git -C $script:RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
if ($dirty.Count -ne 0) { throw "Identity group attestation requires a clean BodyRig checkout." }
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$ReviewRoot = Need-Directory $ReviewRoot "Identity group review root"
$manifest = Need-File (Join-Path $ReviewRoot "identity-group-review-candidates.json") "Identity group review manifest"
$privateIndex = Need-File (Join-Path $ReviewRoot "private-review-index.json") "Private identity group review index"
$reviewIndex = Need-File (Join-Path $ReviewRoot "review-index.html") "Identity group review HTML"

$manifestObject = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
if ([string]$manifestObject.bodyrig_revision -ne $head) {
    throw "Identity group review belongs to revision $([string]$manifestObject.bodyrig_revision), but checkout is $head."
}

$wslRepo = Convert-ToWslPath $script:RepoRoot
$wslReview = Convert-ToWslPath $ReviewRoot

Write-Host "============================================================"
Write-Host "BODYRIG PHOTOREAL V2 - HUMAN IDENTITY GROUP ATTESTATION"
Write-Host "Revision:       $head"
Write-Host "Performer:      $([string]$manifestObject.performer_id)"
Write-Host "Review root:    $ReviewRoot"
Write-Host "Review HTML:    $reviewIndex"
Write-Host "Accept groups:  $($AcceptGroup -join ', ')"
Write-Host "Reject groups:  $($RejectGroup -join ', ')"
Write-Host "Human confirm:  TRUE"
Write-Host "Matching auth:  FALSE"
Write-Host "Training auth:  FALSE"
Write-Host "Production:     FALSE"
Write-Host "============================================================"
Write-Host ""

$wslArgs = @(
    "-d", $Distribution, "--", "env",
    "PYTHONPATH=$wslRepo",
    $LinuxPython, "-m", "bodyrig.photoreal_identity_group_review", "attest",
    "--review-root", $wslReview,
    "--current-revision", $head,
    "--quality-note", $QualityNote,
    "--confirm-identity"
)
foreach ($group in $AcceptGroup) {
    $wslArgs += @("--accept-group", ([string]$group).Trim())
}
foreach ($group in $RejectGroup) {
    $wslArgs += @("--reject-group", ([string]$group).Trim())
}

& wsl.exe @wslArgs
if ($LASTEXITCODE -ne 0) {
    throw "Human identity group attestation failed with exit code $LASTEXITCODE."
}

$receipt = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Identity group attestation receipt"
$result = Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

Write-Host ""
Write-Host "Human identity group attestation: RECORDED"
Write-Host "Accepted:      $($result.accepted_group_count)"
Write-Host "Rejected:      $($result.rejected_group_count)"
Write-Host "Receipt:       $receipt"
Write-Host "Group selection authority: TRUE"
Write-Host "Identity matching:          FALSE"
Write-Host "Teacher training:           FALSE"
Write-Host "Photoreal acceptance:       FALSE"
Write-Host "Production:                 FALSE"
