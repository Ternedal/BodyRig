param(
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [Parameter(Mandatory = $true)][string]$TrackCandidateId,
    [Parameter(Mandatory = $true)][ValidateLength(10, 1000)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmIdentity,
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
    throw "BodyRig multi-performer track attestation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if (-not $ConfirmIdentity.IsPresent) {
    throw "Human source-track identity attestation requires explicit -ConfirmIdentity."
}
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim().Length -lt 10) {
    throw "Human identity QualityNote must contain at least 10 non-whitespace characters."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind human track attestation to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Human track attestation requires an exact clean BodyRig checkout."
}

$ReviewRoot = Need-Directory -Path $ReviewRoot -Label "Multi-performer track review root"
$publicReviewPath = Need-File -Path (Join-Path $ReviewRoot "multiperformer-track-review-candidates.json") -Label "Public track review manifest"
$privateReviewPath = Need-File -Path (Join-Path $ReviewRoot "private-track-review\private-review-index.json") -Label "Private track review index"
$machineReviewPath = Need-File -Path (Join-Path $ReviewRoot "machine-track-review.json") -Label "Machine track review"
try {
    $publicReview = Get-Content -LiteralPath $publicReviewPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
    $privateReview = Get-Content -LiteralPath $privateReviewPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50
} catch { throw "Prepared multi-performer track review evidence is unreadable JSON." }
if ([string]$publicReview.format -ne "bodyrig-photoidentity-multiperformer-track-review-candidates" -or [int]$publicReview.version -ne 1) {
    throw "Public track review manifest format/version is invalid."
}
if ([string]$publicReview.bodyrig_revision -ne $head) {
    throw "Track review belongs to revision $([string]$publicReview.bodyrig_revision), but checkout is $head. Do not rebind human evidence across revisions."
}
if ($publicReview.target_track_selected -ne $false -or $publicReview.human_identity_attestation_required -ne $true) {
    throw "Prepared track review lacks no-target/human-attestation authority."
}
foreach ($field in @(
    "biometric_identity_inference_used",
    "generic_guessing_permitted",
    "target_isolated_source_authority",
    "photoidentity_source_evidence_authority",
    "reconstruction_permitted",
    "production_activation"
)) {
    if ($publicReview.$field -ne $false) { throw "Prepared track review illegally enabled ${field}." }
}
$selected = @($publicReview.tracks | Where-Object { [string]$_.track_candidate_id -eq $TrackCandidateId })
if ($selected.Count -ne 1) { throw "TrackCandidateId is not unique in prepared review: $TrackCandidateId" }
$privateSelected = @($privateReview.tracks | Where-Object { [string]$_.track_candidate_id -eq $TrackCandidateId })
if ($privateSelected.Count -ne 1) { throw "Private review index does not uniquely bind TrackCandidateId: $TrackCandidateId" }
$reviewSheet = Need-File -Path ([string]$privateSelected[0].review_sheet) -Label "Selected source-track review sheet"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidatePython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $candidatePython -PathType Leaf)) { throw "BodyRig checkout Python is missing: $candidatePython" }
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

$receiptPath = Join-Path $ReviewRoot "photoidentity-multiperformer-track-attestation.json"
if (Test-Path -LiteralPath $receiptPath) {
    throw "Human track attestation already exists: $receiptPath"
}

Write-Host "BodyRig multi-performer human track attestation"
Write-Host "Revision:         $head"
Write-Host "Performer:        $([string]$publicReview.performer_id)"
Write-Host "Scene:            $([string]$publicReview.scene_id)"
Write-Host "Track candidate:  $TrackCandidateId"
Write-Host "PHALP track:      $([string]$selected[0].track_id)"
Write-Host "Review sheet:     $reviewSheet"
Write-Host "Human confirmation: TRUE"
Write-Host ""

& $BodyRigPython -m bodyrig.photoidentity_multiperformer_track_attestation `
    --review-root $ReviewRoot `
    --track-candidate-id $TrackCandidateId `
    --current-revision $head `
    --quality-note $QualityNote `
    --confirm-identity
if ($LASTEXITCODE -ne 0) { throw "Human multi-performer track attestation failed with exit code $LASTEXITCODE." }

$receiptPath = Need-File -Path $receiptPath -Label "Human track attestation receipt"
try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
catch { throw "Human track attestation receipt is unreadable JSON." }
if ([string]$receipt.format -ne "bodyrig-photoidentity-multiperformer-track-attestation" -or [int]$receipt.version -ne 1) {
    throw "Human track attestation receipt format/version is invalid."
}
if ([string]$receipt.bodyrig_revision -ne $head -or [string]$receipt.track_candidate_id -ne $TrackCandidateId) {
    throw "Human track attestation receipt lost revision/track binding."
}
if ($receipt.human_identity_attested -ne $true) { throw "Human identity receipt did not record explicit attestation." }
foreach ($field in @(
    "biometric_identity_inference_used",
    "generic_guessing_permitted",
    "target_isolated_source_authority",
    "photoidentity_source_evidence_authority",
    "reconstruction_permitted",
    "production_activation"
)) {
    if ($receipt.$field -ne $false) { throw "Human track attestation illegally enabled ${field}." }
}
$receiptSha = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host ""
Write-Host "BodyRig human source-track identity: ATTESTED"
Write-Host "Selected PHALP track:              $([string]$receipt.selected_track_id)"
Write-Host "Receipt SHA-256:                   $receiptSha"
Write-Host "Receipt:                           $receiptPath"
Write-Host "Biometric inference:               FALSE"
Write-Host "Target-isolated source authority:  FALSE"
Write-Host "Photoidentity evidence authority:  FALSE"
Write-Host "Reconstruction permitted:          FALSE"
Write-Host "Production activation:             FALSE"
Write-Host "Next blocker: build and review target-isolated source evidence before this multi-performer media can enter the photoidentity evidence pool."
