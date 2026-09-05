param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [Parameter(Mandatory = $true)][switch]$ConfirmVisualChecklist,
    [Parameter(Mandatory = $true)][ValidateLength(1, 4000)][string]$QualityNote
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig component visual-review path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig component visual-review path."
}
if (-not $ConfirmVisualChecklist) {
    throw "Component visual review requires explicit -ConfirmVisualChecklist after reviewing full-body anatomy, hair silhouette, face close-up and eye close-up evidence."
}
if ([string]::IsNullOrWhiteSpace($QualityNote)) {
    throw "QualityNote must contain the operator's physical component review."
}
$QualityNote = $QualityNote.Trim()

function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig Git revision is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed while component visual review was being written; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout changed while component visual review was being written; checkout is dirty." }
    return $head
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python 3.11+ executable 'python' was not found. Run this from the validated BodyRig operator environment."
}
$pythonExe = $pythonCommand.Source
$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') {
    throw "Could not verify Python runtime for BodyRig component visual review."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig component visual review requires Python 3.11+; detected $versionText."
}

$previousPythonPath = $env:PYTHONPATH
$reviewPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_component_review_cli `
            --preview-job-id $PreviewJobId `
            --bodyrig-revision $initialHead `
            --confirm-visual-checklist `
            --quality-note $QualityNote)
        if ($LASTEXITCODE -ne 0) {
            throw "Component visual-review CLI failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json -Depth 20 }
    catch { throw "Component visual-review CLI did not return canonical JSON." }
    if ($result.ok -ne $true) { throw "Component visual-review CLI did not report PASS." }
    if ([string]$result.preview_job_id -ne $PreviewJobId) { throw "Component visual-review CLI returned a different preview job id." }
    if ([string]$result.bodyrig_revision -ne $initialHead) { throw "Component visual-review CLI returned a different BodyRig revision." }
    if ([string]$result.candidate_package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Component visual-review CLI returned an invalid candidate package SHA." }
    if ([string]$result.review_vrm_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Component visual-review CLI returned an invalid review VRM SHA." }
    if ($result.promotion_eligibility.body_anatomy -ne $true) { throw "Component visual-review v1 must make only reviewed anatomy promotion-eligible." }
    if ($result.promotion_eligibility.hair -ne $false) { throw "Hair cannot become promotion-eligible before runtime deformation review." }
    if ($result.promotion_eligibility.eyes -ne $false) { throw "Eyes cannot become promotion-eligible while iris authority is review-pending." }
    if ($result.production_activation -ne $false) { throw "Component visual-review receipt must remain independently non-activating." }
    $reviewPath = [string]$result.review_path
    if ([string]::IsNullOrWhiteSpace($reviewPath) -or -not (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
        throw "Component visual-review receipt was not persisted at the returned path."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($reviewPath) -and (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
            Remove-Item -LiteralPath $reviewPath -Force
        }
        throw "BodyRig checkout authority changed after component visual-review write; removed non-authoritative receipt '$reviewPath'. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig component visual review: PASS | preview=$PreviewJobId"
Write-Host "Receipt: $reviewPath"
Write-Host "Anatomy: promotion-eligible"
Write-Host "Hair: visual pass only; runtime deformation review still required"
Write-Host "Eyes: visual pass only; iris authority still required"
Write-Host "Authority: exact six-view preview evidence + clean exact checkout | production_activation=false"
exit 0
