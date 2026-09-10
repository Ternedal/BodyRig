param(
    [Parameter(Mandatory = $true)][string]$IsolationRoot,
    [Parameter(Mandatory = $true)][ValidateLength(10, 1000)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$ConfirmIsolation,
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
    throw "BodyRig target-isolation attestation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if (-not $ConfirmIsolation.IsPresent) {
    throw "Human target-isolation attestation requires explicit -ConfirmIsolation after reviewing every isolation sample."
}
if ([string]::IsNullOrWhiteSpace($QualityNote) -or $QualityNote.Trim().Length -lt 10) {
    throw "Human isolation QualityNote must contain at least 10 non-whitespace characters."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind human target-isolation attestation to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Human target-isolation attestation requires an exact clean BodyRig checkout."
}

$IsolationRoot = Need-Directory -Path $IsolationRoot -Label "Target-isolation review root"
$publicPath = Need-File -Path (Join-Path $IsolationRoot "target-isolation-candidate.json") -Label "Target-isolation candidate manifest"
$privatePath = Need-File -Path (Join-Path $IsolationRoot "private-target-isolation\private-isolation-index.json") -Label "Private target-isolation index"
try {
    $public = Get-Content -LiteralPath $publicPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 70
    $private = Get-Content -LiteralPath $privatePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 70
} catch { throw "Target-isolation review evidence is unreadable JSON." }
if ([string]$public.format -ne "bodyrig-photoidentity-target-isolation-candidate" -or [int]$public.version -ne 1) {
    throw "Target-isolation candidate format/version is invalid."
}
if ([string]$public.isolation_operator_revision -ne $head) {
    throw "Target-isolation candidate belongs to revision $([string]$public.isolation_operator_revision), but checkout is $head. Review from the exact candidate revision."
}
if ($public.human_isolation_review_required -ne $true -or $public.target_isolated_source_authority -ne $false) {
    throw "Target-isolation candidate does not present an unresolved human gate."
}
foreach ($field in @(
    "machine_identity_selection",
    "biometric_identity_inference_used",
    "generic_guessing_permitted",
    "photoidentity_source_evidence_authority",
    "reconstruction_permitted",
    "production_activation"
)) {
    if ($public.$field -ne $false) { throw "Target-isolation candidate illegally enabled ${field}." }
}
$contactSheet = Need-File -Path ([string]$private.contact_sheet) -Label "Target-isolation contact sheet"

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

$receiptPath = Join-Path $IsolationRoot "photoidentity-target-isolation-attestation.json"
if (Test-Path -LiteralPath $receiptPath) { throw "Human target-isolation attestation already exists: $receiptPath" }

Write-Host "BodyRig human target-isolation attestation"
Write-Host "Revision:                         $head"
Write-Host "Performer:                        $([string]$public.performer_id)"
Write-Host "Scene:                            $([string]$public.scene_id)"
Write-Host "Human-attested PHALP track:       $([string]$public.selected_track_id)"
Write-Host "Candidate frames:                 $([int]$public.candidate_frame_count)"
Write-Host "Review contact sheet:             $contactSheet"
Write-Host ("Max machine bbox overlap:          {0:P2}" -f [double]$public.max_other_overlap_fraction)
Write-Host ""
Write-Host "Explicit human claims being recorded:"
Write-Host "  - every shown isolation sample was reviewed"
Write-Host "  - isolated side contains the requested performer"
Write-Host "  - no visible pixels from another performer contaminate the isolated subject evidence"
Write-Host "  - authority applies only to the isolated sampled frame set, not the original multi-person video"
Write-Host ""

& $BodyRigPython -m bodyrig.photoidentity_target_isolation_attestation `
    --isolation-root $IsolationRoot `
    --current-revision $head `
    --quality-note $QualityNote `
    --confirm-isolation
if ($LASTEXITCODE -ne 0) { throw "Human target-isolation attestation failed with exit code $LASTEXITCODE." }

$receiptPath = Need-File -Path $receiptPath -Label "Human target-isolation attestation receipt"
try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 70 }
catch { throw "Human target-isolation attestation receipt is unreadable JSON." }
if ([string]$receipt.format -ne "bodyrig-photoidentity-target-isolation-attestation" -or [int]$receipt.version -ne 1) {
    throw "Human target-isolation receipt format/version is invalid."
}
if ([string]$receipt.human_review_revision -ne $head -or [string]$receipt.isolation_operator_revision -ne $head) {
    throw "Human target-isolation receipt lost exact review revision binding."
}
if ([string]$receipt.authority_scope -ne "isolated-sampled-frame-set-only") {
    throw "Human target-isolation receipt authority scope changed."
}
if ($receipt.human_isolation_attested -ne $true -or $receipt.target_isolated_source_authority -ne $true) {
    throw "Human target-isolation receipt did not grant the reviewed frame-set authority."
}
foreach ($field in @(
    "biometric_identity_inference_used",
    "generic_guessing_permitted",
    "photoidentity_source_evidence_authority",
    "reconstruction_permitted",
    "production_activation"
)) {
    if ($receipt.$field -ne $false) { throw "Human target-isolation receipt illegally enabled ${field}." }
}
$receiptSha = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host ""
Write-Host "BodyRig target-isolated sampled frame set: ATTESTED"
Write-Host "Authority scope:                  $([string]$receipt.authority_scope)"
Write-Host "Isolated frame count:             $([int]$receipt.isolated_frame_count)"
Write-Host "Receipt SHA-256:                  $receiptSha"
Write-Host "Receipt:                          $receiptPath"
Write-Host "Target-isolated source authority: TRUE"
Write-Host "Photoidentity source authority:   FALSE"
Write-Host "Reconstruction permitted:         FALSE"
Write-Host "Production activation:            FALSE"
Write-Host "Next blocker: a separate importer/analyzer contract must consume only these attested isolated frames before they can contribute photoidentity evidence."
