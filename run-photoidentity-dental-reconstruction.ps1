param(
    [Parameter(Mandatory = $true)][string]$SweepRoot,
    [Parameter(Mandatory = $true)][string]$AdapterConfig,
    [string]$PrivateReviewManifest = "",
    [string]$OutputDir = "",
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
    throw "BodyRig photoidentity dental reconstruction operator is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not establish exact BodyRig Git authority." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($head -notmatch '^[0-9a-f]{40}$' -or $LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Dental reconstruction requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else { $BodyRigPython = Need-Executable -Value "" -Fallback "python" -Label "BodyRig Python" }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$SweepRoot = Need-Directory -Path $SweepRoot -Label "Photoidentity sweep root"
$AdapterConfig = Need-File -Path $AdapterConfig -Label "Dental reconstruction adapter config"
if ([string]::IsNullOrWhiteSpace($PrivateReviewManifest)) {
    $PrivateReviewManifest = Join-Path $SweepRoot "private-fine-identity-review-manifest.json"
}
$PrivateReviewManifest = Need-File -Path $PrivateReviewManifest -Label "Private fine-identity review manifest"
$attestation = Need-File -Path (Join-Path $SweepRoot "photoidentity-fine-identity-attestation.json") -Label "Fine-identity attestation"
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $SweepRoot "private-dental-reconstruction"
}
if (Test-Path -LiteralPath $OutputDir) {
    throw "Dental reconstruction output is create-only and already exists: $OutputDir"
}

Write-Host "BodyRig source-derived dental reconstruction"
Write-Host "Revision: $head"
Write-Host "Input authority: exact reviewed oral/teeth PhotoIdentity evidence"
Write-Host "Generic dental fallback: FALSE"
Write-Host "Human review required: TRUE"
Write-Host "Promotion authority: FALSE"
Write-Host "Production activation: FALSE"
Write-Host ""

$pythonArgs = @(
    "-m", "bodyrig.photoidentity_dental_reconstruction",
    "--private-manifest", $PrivateReviewManifest,
    "--attestation", $attestation,
    "--config", $AdapterConfig,
    "--output-dir", $OutputDir,
    "--bodyrig-revision", $head
)
& $BodyRigPython @pythonArgs
if ($LASTEXITCODE -ne 0) {
    throw "Source-derived dental reconstruction failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Private dental candidate workspace: $OutputDir"
Write-Host ("Candidate VRM: " + (Join-Path $OutputDir "adapter-output\dental-source.vrm"))
Write-Host "No face-secondary promotion or production authority has been granted."
