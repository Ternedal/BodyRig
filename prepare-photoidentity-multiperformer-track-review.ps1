param(
    [Parameter(Mandatory = $true)][string]$DiscoveryRoot,
    [Parameter(Mandatory = $true)][string]$SourceCandidateId,
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
    throw "BodyRig multi-performer track review preparation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]).Trim() -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Could not bind multi-performer track review to exact BodyRig Git HEAD."
}
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Multi-performer track review preparation requires an exact clean BodyRig checkout."
}

$DiscoveryRoot = Need-Directory -Path $DiscoveryRoot -Label "Multi-performer discovery root"
$discoveryManifest = Need-File -Path (Join-Path $DiscoveryRoot "multiperformer-source-candidates.json") -Label "Multi-performer discovery manifest"
try { $discovery = Get-Content -LiteralPath $discoveryManifest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
catch { throw "Multi-performer discovery manifest is unreadable JSON." }
if ([string]$discovery.format -ne "bodyrig-photoidentity-multiperformer-source-discovery" -or [int]$discovery.version -ne 1) {
    throw "Multi-performer discovery manifest format/version is invalid."
}
if ([string]$discovery.bodyrig_revision -ne $head) {
    throw "Multi-performer discovery belongs to revision $([string]$discovery.bodyrig_revision), but checkout is $head. Do not rebind human source evidence across revisions."
}
if ($discovery.stash_inventory_exhausted -ne $true -or $discovery.target_track_selected -ne $false) {
    throw "Multi-performer discovery lacks exhaustive/no-target authority."
}
$candidate = @($discovery.candidates | Where-Object { [string]$_.candidate_id -eq $SourceCandidateId })
if ($candidate.Count -ne 1) { throw "Source candidate id is not unique in discovery: $SourceCandidateId" }

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
    $OutputDir = Join-Path $DiscoveryRoot ("track-reviews\" + $SourceCandidateId)
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$repoBoundary = $repoRoot + [IO.Path]::DirectorySeparatorChar
if ([string]::Equals($OutputDir, $repoRoot, [StringComparison]::OrdinalIgnoreCase) -or $OutputDir.StartsWith($repoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Track review output must be outside the BodyRig Git checkout."
}
if (Test-Path -LiteralPath $OutputDir) { throw "Track review output already exists: $OutputDir" }

Write-Host "BodyRig multi-performer track review preparation"
Write-Host "Revision:         $head"
Write-Host "Performer:        $([string]$discovery.performer_id)"
Write-Host "Source candidate: $SourceCandidateId"
Write-Host "Scene:            $([string]$candidate[0].scene_id)"
Write-Host "PHALP target:     NONE (human decision required)"
Write-Host "Output:           $OutputDir"
Write-Host ""

& $BodyRigPython -m bodyrig.photoidentity_multiperformer_review_prepare `
    --discovery-root $DiscoveryRoot `
    --source-candidate-id $SourceCandidateId `
    --output-dir $OutputDir `
    --ffmpeg $Ffmpeg `
    --python $externalPython `
    --repo $fourDRepo `
    --phalp-repo $phalpRepo `
    --distribution $distribution `
    --wsl-exe $WslExe
if ($LASTEXITCODE -ne 0) { throw "Multi-performer track review preparation failed with exit code $LASTEXITCODE." }

$publicReviewPath = Need-File -Path (Join-Path $OutputDir "multiperformer-track-review-candidates.json") -Label "Track review manifest"
$privateReviewPath = Need-File -Path (Join-Path $OutputDir "private-track-review\private-review-index.json") -Label "Private track review index"
try {
    $publicReview = Get-Content -LiteralPath $publicReviewPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40
    $privateReview = Get-Content -LiteralPath $privateReviewPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 40
} catch { throw "Prepared track review evidence is unreadable JSON." }
if ([string]$publicReview.bodyrig_revision -ne $head -or $publicReview.target_track_selected -ne $false) {
    throw "Prepared track review crossed revision/target authority boundary."
}

Write-Host ""
Write-Host "========== SOURCE TRACKS FOR HUMAN IDENTITY REVIEW =========="
if ([int]$publicReview.track_candidate_count -eq 0) {
    Write-Host "No PHALP track with enough actual observations was available; this source remains unresolved."
} else {
    foreach ($track in @($publicReview.tracks)) {
        $privateTrack = @($privateReview.tracks | Where-Object { [string]$_.track_candidate_id -eq [string]$track.track_candidate_id })
        if ($privateTrack.Count -ne 1) { throw "Private review sheet mapping is incomplete." }
        Write-Host ("{0} | PHALP={1} | observations={2} | samples={3}" -f `
            [string]$track.track_candidate_id, [string]$track.track_id, [int]$track.observation_count, [int]$track.review_sample_count)
        Write-Host ("  Review sheet: {0}" -f [string]$privateTrack[0].review_sheet)
    }
    Write-Host ""
    Write-Host "Review the sheets. Only after visually confirming the requested performer, record exactly one listed TrackCandidateId with record-photoidentity-multiperformer-track-attestation.ps1."
}
Write-Host "Machine identity selection: FALSE"
Write-Host "Biometric identity inference: FALSE"
Write-Host "Target-isolated source authority: FALSE"
Write-Host "Reconstruction permitted: FALSE"
