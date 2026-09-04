param(
    [Parameter(Mandatory = $true)][ValidateLength(3, 160)][string]$BodyId,
    [Parameter(Mandatory = $true)][switch]$ConfirmQualityChecklist,
    [Parameter(Mandatory = $true)][ValidateLength(1, 4000)][string]$QualityNote
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig high-fidelity human review path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig high-fidelity human review path."
}
if (-not $ConfirmQualityChecklist) {
    throw "High-fidelity human review requires explicit -ConfirmQualityChecklist after reviewing identity, anatomy, skin, hair, eyes, face-secondary, full-body multiview and face close-up evidence."
}
if ([string]::IsNullOrWhiteSpace($QualityNote)) {
    throw "QualityNote must contain the operator's physical high-fidelity review."
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
        throw "BodyRig checkout revision changed while high-fidelity human review was being written; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout changed while high-fidelity human review was being written; checkout is dirty." }
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
    throw "Could not verify Python runtime for BodyRig high-fidelity review."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig high-fidelity review requires Python 3.11+; detected $versionText."
}

$previousPythonPath = $env:PYTHONPATH
$reviewPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_human_review_cli `
            --body-id $BodyId `
            --confirm-quality-checklist `
            --quality-note $QualityNote)
        if ($LASTEXITCODE -ne 0) {
            throw "High-fidelity human review CLI failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json }
    catch { throw "High-fidelity human review CLI did not return canonical JSON." }
    if ($result.ok -ne $true) { throw "High-fidelity human review CLI did not report PASS." }
    if ([string]$result.body_id -ne $BodyId) { throw "High-fidelity human review CLI returned a different body id." }
    if ([string]$result.package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "High-fidelity human review CLI returned an invalid package SHA." }
    if ([string]$result.component_state_sha256 -notmatch '^[0-9a-f]{64}$') { throw "High-fidelity human review CLI returned an invalid component-state SHA." }
    if ($result.production_activation -ne $false) { throw "High-fidelity human review receipt must remain independently non-activating." }
    $reviewPath = [string]$result.review_path
    if ([string]::IsNullOrWhiteSpace($reviewPath) -or -not (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
        throw "High-fidelity human review receipt was not persisted at the returned path."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($reviewPath) -and (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
            Remove-Item -LiteralPath $reviewPath -Force
        }
        throw "BodyRig checkout authority changed after high-fidelity human review write; removed non-authoritative receipt '$reviewPath'. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity human review: PASS | body=$BodyId"
Write-Host "Receipt: $reviewPath"
Write-Host "Authority: package SHA + component-state SHA + bodyrig-high-fidelity-human-review-v1 | production_activation=false"
exit 0
