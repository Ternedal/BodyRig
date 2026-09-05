param(
    [Parameter(Mandatory = $true)][string]$PreparationDir,
    [Parameter(Mandatory = $true)][string]$RuntimeDir,
    [Parameter(Mandatory = $true)][string]$RenderDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][string]$QualityNote,
    [Parameter(Mandatory = $true)][switch]$NeutralFacePreserved,
    [Parameter(Mandatory = $true)][switch]$EyebrowSourceAppearanceAcceptable,
    [Parameter(Mandatory = $true)][switch]$LipBoundarySourceAppearanceAcceptable,
    [Parameter(Mandatory = $true)][switch]$MouthOpenPoseReviewed,
    [Parameter(Mandatory = $true)][switch]$MouthInteriorVisibleAndPlausible,
    [Parameter(Mandatory = $true)][switch]$UpperTeethVisibleAndPlausible,
    [Parameter(Mandatory = $true)][switch]$LowerTeethVisibleAndJawBound,
    [Parameter(Mandatory = $true)][switch]$TeethNoObviousClippingAtOpenPose,
    [Parameter(Mandatory = $true)][switch]$EyelashesVisibleAndPlausible,
    [Parameter(Mandatory = $true)][switch]$EyelashesNoObviousEyeSurfaceClipping,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Face-secondary human review is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Invoke-ReviewPython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& $BodyRigPython @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label failed: $($raw -join [Environment]::NewLine)" }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "$Label returned unreadable JSON." }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$PreparationDir = Need-Directory -Path $PreparationDir -Label "Face-secondary preview preparation"
$RuntimeDir = Need-Directory -Path $RuntimeDir -Label "Face-secondary review runtime"
$RenderDir = Need-Directory -Path $RenderDir -Label "Face-secondary Windows render evidence"
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Face-secondary human review output already exists; refusing overwrite: $OutputDir" }
if ([string]::IsNullOrWhiteSpace($QualityNote)) { throw "A non-empty face-secondary quality note is required." }

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]) -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve exact BodyRig HEAD." }
$head = ([string]$headRaw[0]).ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Face-secondary human review requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"
$created = $false

try {
    $args = @(
        "-m", "bodyrig.high_fidelity_face_secondary_review_cli", "record",
        "--preparation-dir", $PreparationDir,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $RenderDir,
        "--output-dir", $OutputDir,
        "--bodyrig-revision", $head,
        "--quality-note", $QualityNote,
        "--neutral-face-preserved",
        "--eyebrow-source-appearance-acceptable",
        "--lip-boundary-source-appearance-acceptable",
        "--mouth-open-pose-reviewed",
        "--mouth-interior-visible-and-plausible",
        "--upper-teeth-visible-and-plausible",
        "--lower-teeth-visible-and-jaw-bound",
        "--teeth-no-obvious-clipping-at-open-pose",
        "--eyelashes-visible-and-plausible",
        "--eyelashes-no-obvious-eye-surface-clipping"
    )
    [void](Invoke-ReviewPython -Arguments $args -Label "Face-secondary human review recording")
    $created = $true

    $headAfterRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
    $dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headAfterRaw.Count -ne 1 -or ([string]$headAfterRaw[0]).ToLowerInvariant() -ne $head -or $dirtyAfter.Count -gt 0) {
        throw "BodyRig checkout changed during face-secondary human review; refusing stale authority."
    }

    [void](Invoke-ReviewPython -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_review_cli", "verify",
        "--preparation-dir", $PreparationDir,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $RenderDir,
        "--output-dir", $OutputDir
    ) -Label "Face-secondary human review post-write verification")
} catch {
    if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) { Remove-Item -LiteralPath $OutputDir -Recurse -Force }
    throw
}

Write-Host "BodyRig face-secondary human review: PASS"
Write-Host "Output: $OutputDir"
Write-Host "Teeth: upper/lower visibility + jaw binding + mouth-open clipping explicitly reviewed"
Write-Host "Authority: promotion-eligible only; package not mutated; production remains false"
exit 0
