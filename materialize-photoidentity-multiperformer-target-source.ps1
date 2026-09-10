param(
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
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
function Read-ExactHead {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $raw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1 -or ([string]$raw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Could not bind target-isolated source evidence to exact BodyRig Git HEAD."
    }
    return ([string]$raw[0]).Trim().ToLowerInvariant()
}
function Assert-CleanCheckout {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
        throw "Target-isolated source materialization requires an exact clean BodyRig checkout."
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig multi-performer target source materialization is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Read-ExactHead -RepoRoot $repoRoot
Assert-CleanCheckout -RepoRoot $repoRoot
$ReviewRoot = Need-Directory -Path $ReviewRoot -Label "Multi-performer track review root"
$null = Need-File -Path (Join-Path $ReviewRoot "photoidentity-multiperformer-track-attestation.json") -Label "Human multi-performer track attestation"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidatePython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidatePython -PathType Leaf)) {
        throw "BodyRig checkout Python is missing: $candidatePython"
    }
    $BodyRigPython = $candidatePython
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actualRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualRaw.Count -ne 1) { throw "Could not verify checkout-bound BodyRig Python." }
$actualModule = [IO.Path]::GetFullPath(([string]$actualRaw[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ReviewRoot "target-isolated-source"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir, $repoRoot, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Target-isolated source output must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Target-isolated source output already exists: $OutputDir" }

Write-Host "BodyRig multi-performer target source isolation"
Write-Host "Revision:     $head"
Write-Host "Review root:  $ReviewRoot"
Write-Host "Output:       $OutputDir"
Write-Host "Mode:         source-only | exact human-reviewed PHALP samples"
Write-Host "Interpolation: FALSE"
Write-Host "Generative pixels: FALSE"
Write-Host "Reconstruction: FALSE"
Write-Host ""

$created = $false
try {
    & $BodyRigPython -m bodyrig.photoidentity_multiperformer_target_isolation `
        --review-root $ReviewRoot `
        --output-dir $OutputDir `
        --current-revision $head
    if ($LASTEXITCODE -ne 0) { throw "Multi-performer target source isolation failed with exit code $LASTEXITCODE." }
    $created = $true

    $manifestPath = Need-File -Path (Join-Path $OutputDir "multiperformer-target-isolated-source.json") -Label "Target-isolated source manifest"
    try { $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
    catch { throw "Target-isolated source manifest is unreadable JSON." }
    if ([string]$manifest.format -ne "bodyrig-photoidentity-multiperformer-target-isolated-source" -or [int]$manifest.version -ne 1) {
        throw "Target-isolated source manifest format/version is invalid."
    }
    if ([string]$manifest.bodyrig_revision -ne $head) { throw "Target-isolated source manifest belongs to a different BodyRig revision." }
    if ($manifest.target_track_identity_attested -ne $true -or $manifest.source_frames_human_review_bound -ne $true -or $manifest.all_samples_phalp_observed -ne $true) {
        throw "Target-isolated source manifest lacks required human/source/PHALP authority."
    }
    if ($manifest.target_isolated_source_authority -ne $true) { throw "Target-isolated source authority was not granted." }
    foreach ($field in @(
        "bbox_interpolation_used",
        "source_pixels_resized",
        "occlusion_removal_used",
        "generative_pixels_used",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "photoidentity_source_evidence_authority",
        "reconstruction_permitted",
        "production_activation"
    )) {
        if ($manifest.$field -ne $false) { throw "Target-isolated source manifest crossed authority boundary: $field" }
    }
    if ([int]$manifest.sample_count -lt 1) { throw "Target-isolated source manifest contains no samples." }

    $headAfter = Read-ExactHead -RepoRoot $repoRoot
    Assert-CleanCheckout -RepoRoot $repoRoot
    if ($headAfter -ne $head) { throw "BodyRig checkout revision changed during target source materialization." }

    Write-Host ""
    Write-Host "BodyRig multi-performer target source isolation: PASS"
    Write-Host "Manifest:      $manifestPath"
    Write-Host "Samples:       $([int]$manifest.sample_count)"
    Write-Host "Target source: AUTHORITY TRUE"
    Write-Host "Photoidentity sufficiency: FALSE"
    Write-Host "Reconstruction permitted: FALSE"
    Write-Host "Next: source-only detail enrichment of these exact target pixels."
} catch {
    if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
