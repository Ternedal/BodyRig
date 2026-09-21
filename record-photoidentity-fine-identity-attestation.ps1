param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string]$PrivateReviewManifest,
    [Parameter(Mandatory = $true)][string]$ReviewedBy,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmOralTeethPhotoidentity,
    [Parameter(Mandatory = $true)][switch]$ConfirmChestBreastShapePhotoidentity,
    [Parameter(Mandatory = $true)][switch]$ConfirmNippleAreolaPhotoidentity,
    [Parameter(Mandatory = $true)][switch]$ConfirmIntimateAnatomyPhotoidentity,
    [Parameter(Mandatory = $true)][switch]$ConfirmDistinctiveMarkersPhotoidentity,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-Executable {
    param([string]$Value,[string]$Fallback,[string]$Label)
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $Fallback } else { $Value }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "$Label executable not found: $candidate" }
    return $command.Source
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig fine-identity photoidentity review is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

foreach ($confirmation in @(
    $ConfirmOralTeethPhotoidentity,
    $ConfirmChestBreastShapePhotoidentity,
    $ConfirmNippleAreolaPhotoidentity,
    $ConfirmIntimateAnatomyPhotoidentity,
    $ConfirmDistinctiveMarkersPhotoidentity
)) {
    if (-not $confirmation.IsPresent) {
        throw "Photoidentical fine-identity review requires all five explicit confirmation switches."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($head -notmatch '^[0-9a-f]{40}$' -or $LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Fine-identity photoidentity review requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$PrivateReviewManifest = Need-File -Path $PrivateReviewManifest -Label "Private fine-identity review manifest"
$anatomyObservations = Need-File -Path (Join-Path $SweepRoot "anatomy-attested-evidence\photoidentity-observations.json") -Label "Anatomy observations"
$anatomyReport = Need-File -Path (Join-Path $SweepRoot "anatomy-attested-evidence\photoidentity-evidence.json") -Label "Anatomy sufficiency report"
$output = Join-Path $SweepRoot "photoidentity-fine-identity-attestation.json"

Write-Host "BodyRig photoidentical fine-identity source attestation"
Write-Host "Revision: $head"
Write-Host "Domains: oral/teeth, chest/breast shape, nipple/areola, intimate anatomy, distinctive markers"
Write-Host "Generic guessing: FALSE"
Write-Host "Production activation: FALSE"
Write-Host ""

& $BodyRigPython -m bodyrig.photoidentity_fine_identity_attestation `
    --private-manifest $PrivateReviewManifest `
    --anatomy-observations $anatomyObservations `
    --anatomy-report $anatomyReport `
    --reviewed-by $ReviewedBy `
    --quality-note $QualityNote `
    --confirm-oral-teeth-photoidentity `
    --confirm-chest-breast-shape-photoidentity `
    --confirm-nipple-areola-photoidentity `
    --confirm-intimate-anatomy-photoidentity `
    --confirm-distinctive-markers-photoidentity `
    --output $output
if ($LASTEXITCODE -ne 0) { throw "BodyRig fine-identity source attestation failed with exit code $LASTEXITCODE." }

Write-Host ""
Write-Host "Fine-identity source authority recorded: $output"
Write-Host "This does NOT grant reconstruction, photoreal acceptance, or production authority."
