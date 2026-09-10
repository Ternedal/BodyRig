param(
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$OutputDir = "",
    [string]$BodyRigPython = "",
    [string]$RigSetupReport = "",
    [string]$Ffmpeg = "",
    [string]$WslExe = "wsl.exe"
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
    throw "BodyRig target-isolation preparation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind target-isolation preparation to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Target-isolation preparation requires an exact clean BodyRig checkout."
}

$ReviewRoot = Need-Directory -Path $ReviewRoot -Label "Multi-performer human track review root"
$trackReceiptPath = Need-File -Path (Join-Path $ReviewRoot "photoidentity-multiperformer-track-attestation.json") -Label "Human source-track attestation"
try { $trackReceipt = Get-Content -LiteralPath $trackReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 50 }
catch { throw "Human source-track attestation is unreadable JSON." }
if ([string]$trackReceipt.format -ne "bodyrig-photoidentity-multiperformer-track-attestation" -or [int]$trackReceipt.version -ne 1) {
    throw "Human source-track attestation format/version is invalid."
}
if ($trackReceipt.human_identity_attested -ne $true) { throw "Human source-track identity has not been attested." }
foreach ($field in @(
    "biometric_identity_inference_used",
    "generic_guessing_permitted",
    "target_isolated_source_authority",
    "photoidentity_source_evidence_authority",
    "reconstruction_permitted",
    "production_activation"
)) {
    if ($trackReceipt.$field -ne $false) { throw "Upstream human source-track receipt illegally enabled ${field}." }
}
$attestationRevision = ([string]$trackReceipt.bodyrig_revision).Trim().ToLowerInvariant()
if ($attestationRevision -notmatch '^[0-9a-f]{40}$') { throw "Human source-track attestation revision is invalid." }
& git -C $repoRoot cat-file -e "$attestationRevision`^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Human source-track attestation revision is not present in this checkout: $attestationRevision"
}
& git -C $repoRoot merge-base --is-ancestor $attestationRevision $head
$ancestorExit = $LASTEXITCODE
if ($ancestorExit -eq 1) {
    throw "Human source-track attestation revision $attestationRevision is not an ancestor of current HEAD $head. Refusing cross-lineage evidence reuse."
}
if ($ancestorExit -ne 0) { throw "Could not verify human source-track revision ancestry." }

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

if ([string]::IsNullOrWhiteSpace($RigSetupReport)) {
    $RigSetupReport = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
}
$RigSetupReport = Need-File -Path $RigSetupReport -Label "BodyRig rig setup report"
$rigRaw = @(& $BodyRigPython -m bodyrig.rig_setup $RigSetupReport 2>&1)
if ($LASTEXITCODE -ne 0 -or $rigRaw.Count -ne 1) { throw "BodyRig rig setup failed strict nested-evidence validation." }
try { $rig = ([string]$rigRaw[0]) | ConvertFrom-Json -Depth 30 }
catch { throw "BodyRig rig setup validator returned unreadable JSON." }

$sithSetupPath = Need-File -Path ([string]$rig.high_fidelity.setup_report) -Label "Validated SiTH setup report"
try { $sithSetup = Get-Content -LiteralPath $sithSetupPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "Validated SiTH setup report is unreadable JSON." }
$distribution = ([string]$sithSetup.distribution).Trim()
if ([string]::IsNullOrWhiteSpace($distribution)) { throw "Validated rig setup lacks WSL distribution authority." }
$externalPython = ([string]$rig.recovery.external_python).Trim()
$fourDRepo = ([string]$rig.recovery.four_d_humans_repo).Trim()
$phalpRepo = ([string]$rig.recovery.phalp_repo).Trim()
foreach ($pair in @(
    @("Recovery Python", $externalPython),
    @("4D-Humans repo", $fourDRepo),
    @("PHALP repo", $phalpRepo)
)) {
    if ([string]::IsNullOrWhiteSpace([string]$pair[1]) -or -not ([string]$pair[1]).StartsWith("/")) {
        throw "$([string]$pair[0]) is not an absolute WSL path in validated rig authority: $([string]$pair[1])"
    }
}
$Ffmpeg = Need-Executable -Value $Ffmpeg -Fallback "ffmpeg" -Label "FFmpeg"
$WslExe = Need-Executable -Value $WslExe -Fallback "wsl.exe" -Label "WSL"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ReviewRoot "target-isolation"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir, $repoRoot, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Target-isolation evidence must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Target-isolation output already exists: $OutputDir" }

Write-Host "BodyRig target-isolation preparation"
Write-Host "Current revision:       $head"
Write-Host "Track attestation rev:  $attestationRevision"
Write-Host "Performer:              $([string]$trackReceipt.performer_id)"
Write-Host "Scene:                  $([string]$trackReceipt.scene_id)"
Write-Host "Human-attested track:   $([string]$trackReceipt.selected_track_id)"
Write-Host "Machine identity choice: FALSE"
Write-Host "Output:                 $OutputDir"
Write-Host ""

& $BodyRigPython -m bodyrig.photoidentity_target_isolation_prepare `
    --review-root $ReviewRoot `
    --output-dir $OutputDir `
    --current-revision $head `
    --ffmpeg $Ffmpeg `
    --python $externalPython `
    --repo $fourDRepo `
    --phalp-repo $phalpRepo `
    --distribution $distribution `
    --wsl-exe $WslExe
if ($LASTEXITCODE -ne 0) { throw "Target-isolation preparation failed with exit code $LASTEXITCODE." }

$publicPath = Need-File -Path (Join-Path $OutputDir "target-isolation-candidate.json") -Label "Target-isolation candidate manifest"
$privatePath = Need-File -Path (Join-Path $OutputDir "private-target-isolation\private-isolation-index.json") -Label "Private target-isolation index"
try {
    $public = Get-Content -LiteralPath $publicPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
    $private = Get-Content -LiteralPath $privatePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 60
} catch { throw "Target-isolation preparation returned unreadable JSON evidence." }
if ([string]$public.format -ne "bodyrig-photoidentity-target-isolation-candidate" -or [int]$public.version -ne 1) {
    throw "Target-isolation candidate format/version is invalid."
}
if ([string]$public.isolation_operator_revision -ne $head -or [string]$public.attestation_revision -ne $attestationRevision) {
    throw "Target-isolation candidate lost revision-chain binding."
}
if ($public.human_isolation_review_required -ne $true -or $public.target_isolated_source_authority -ne $false) {
    throw "Target-isolation candidate crossed human authority boundary."
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

Write-Host ""
Write-Host "========== TARGET-ISOLATION HUMAN REVIEW =========="
Write-Host "Review contact sheet:             $contactSheet"
Write-Host "Candidate frames:                 $([int]$public.candidate_frame_count)"
Write-Host ("Max other-track bbox overlap:      {0:P2}" -f [double]$public.max_other_overlap_fraction)
Write-Host ("P95 other-track bbox overlap:      {0:P2}" -f [double]$public.p95_other_overlap_fraction)
Write-Host "High-overlap observed states:      $([int]$public.high_overlap_state_count)"
Write-Host "Severe-overlap observed states:    $([int]$public.severe_overlap_state_count)"
Write-Host ""
if ([int]$public.severe_overlap_state_count -gt 0) {
    Write-Warning "PHALP bbox overlap indicates possible cross-person contamination. This is machine comparison evidence only; inspect every shown isolation sample before deciding."
}
Write-Host "Machine isolation status:          REVIEW CANDIDATE ONLY"
Write-Host "Target-isolated source authority:  FALSE"
Write-Host "Photoidentity source authority:    FALSE"
Write-Host "Reconstruction permitted:          FALSE"
Write-Host ""
Write-Host "After reviewing every sample, use record-photoidentity-target-isolation-attestation.ps1 only if the isolated side contains the requested performer and no visible cross-person contamination."
