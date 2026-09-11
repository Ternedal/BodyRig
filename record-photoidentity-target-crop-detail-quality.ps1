param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [string]$EnrichmentRoot = "",
    [Parameter(Mandatory = $true)][string[]]$DetailRef,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmQuality,
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

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig target-crop source-detail quality attestation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if (-not $ConfirmQuality) { throw "Explicit -ConfirmQuality is required." }
if ($DetailRef.Count -lt 1) { throw "At least one -DetailRef is required." }
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim().Length -lt 20) {
    throw "A real source-detail quality note is required."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind source-detail attestation to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Target-crop source-detail quality attestation requires an exact clean BodyRig checkout."
}

$CandidateRoot = Need-Directory -Path $CandidateRoot -Label "Human-reviewed target-isolation candidate root"
$null = Need-File -Path (Join-Path $CandidateRoot "photoidentity-multiperformer-target-isolation-attestation.json") -Label "Human target-isolation receipt"
if ([string]::IsNullOrWhiteSpace($EnrichmentRoot)) {
    $EnrichmentRoot = Join-Path $CandidateRoot "target-crop-detail-enrichment"
}
$EnrichmentRoot = Need-Directory -Path $EnrichmentRoot -Label "Target-crop detail enrichment root"
$null = Need-File -Path (Join-Path $EnrichmentRoot "target-crop-detail-enrichment.json") -Label "Target-crop detail enrichment receipt"
$null = Need-File -Path (Join-Path $EnrichmentRoot "private-analysis\private-analysis-index.json") -Label "Private target-crop analysis index"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $BodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "Checkout BodyRig module"
$actualRaw = @(& $BodyRigPython -c "import pathlib,bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $actualRaw.Count -ne 1) { throw "Could not verify checkout-bound BodyRig Python." }
$actualModule = [IO.Path]::GetFullPath(([string]$actualRaw[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports from a different checkout: $actualModule"
}

$args = @(
    "-m", "bodyrig.photoidentity_target_crop_quality_attestation",
    "--candidate-root", $CandidateRoot,
    "--enrichment-root", $EnrichmentRoot,
    "--current-revision", $head,
    "--quality-note", $QualityNote,
    "--confirm-quality"
)
foreach ($ref in $DetailRef) {
    $args += @("--detail-ref", [string]$ref)
}

Write-Host "BodyRig target-crop source-detail quality attestation"
Write-Host "Revision: $head"
Write-Host "Candidate root: $CandidateRoot"
Write-Host "Enrichment root: $EnrichmentRoot"
Write-Host "Selected detail refs: $($DetailRef.Count)"
Write-Host "Authority after this step: source-detail quality only"
Write-Host "Photoidentity sufficiency: FALSE"
Write-Host "Reconstruction: FALSE"
Write-Host ""

& $BodyRigPython @args
if ($LASTEXITCODE -ne 0) { throw "Target-crop source-detail quality attestation failed with exit code $LASTEXITCODE." }

$receiptPath = Need-File -Path (Join-Path $EnrichmentRoot "photoidentity-target-crop-detail-quality-attestation.json") -Label "Target-crop source-detail quality receipt"
try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60 }
catch { throw "Target-crop source-detail quality receipt is unreadable JSON." }
if (
    [string]$receipt.bodyrig_revision -ne $head -or
    $receipt.human_source_detail_quality_attested -ne $true -or
    $receipt.source_detail_quality_authority -ne $true -or
    $receipt.photoidentity_source_evidence_authority -ne $false -or
    $receipt.generic_guessing_permitted -ne $false -or
    $receipt.reconstruction_permitted -ne $false -or
    $receipt.production_activation -ne $false
) {
    throw "Target-crop source-detail quality receipt crossed authority boundary."
}
$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0) {
    Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
    throw "Checkout changed during source-detail attestation; newly created receipt was removed."
}

Write-Host ""
Write-Host "BodyRig target-crop source-detail quality: RECORDED"
Write-Host "Receipt: $receiptPath"
Write-Host "Domains: $(@($receipt.selected_domains) -join ', ')"
Write-Host "Source detail quality authority: TRUE"
Write-Host "Photoidentity source evidence authority: FALSE"
Write-Host "Reconstruction permitted: FALSE"
