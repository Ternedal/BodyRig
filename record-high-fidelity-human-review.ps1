param(
    [string]$BodyId = "",
    [string]$PackagePath = "",
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

$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
$hasPackage = -not [string]::IsNullOrWhiteSpace($PackagePath)
if ($hasBodyId -eq $hasPackage) {
    throw "Specify exactly one high-fidelity review source: -BodyId for an installed package OR -PackagePath for an exact promoted candidate package."
}
if ($hasBodyId -and $BodyId -notmatch '^[A-Za-z0-9._-]{3,160}$') {
    throw "BodyId is not canonical."
}
if ($hasPackage) {
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw "High-fidelity package not found: $PackagePath" }
    $PackagePath = (Resolve-Path -LiteralPath $PackagePath).Path
}

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

$sourceArgs = if ($hasBodyId) { @("--body-id", $BodyId) } else { @("--package", $PackagePath) }
$expectedPackageSha = if ($hasPackage) { (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant() } else { "" }
$previousPythonPath = $env:PYTHONPATH
$reviewPath = ""
$result = $null
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_human_review_cli @sourceArgs `
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
    if ($hasBodyId -and [string]$result.body_id -ne $BodyId) { throw "High-fidelity human review CLI returned a different body id." }
    if ([string]$result.package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "High-fidelity human review CLI returned an invalid package SHA." }
    if ($hasPackage -and [string]$result.package_sha256 -ne $expectedPackageSha) { throw "High-fidelity human review CLI reviewed different package bytes." }
    if ([string]$result.component_state_sha256 -notmatch '^[0-9a-f]{64}$') { throw "High-fidelity human review CLI returned an invalid component-state SHA." }
    if ($result.production_activation -ne $false) { throw "High-fidelity human review receipt must remain independently non-activating." }
    $reviewPath = [string]$result.review_path
    if ([string]::IsNullOrWhiteSpace($reviewPath) -or -not (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
        throw "High-fidelity human review receipt was not persisted at the returned path."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
        if ($hasPackage -and (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedPackageSha) {
            throw "Reviewed high-fidelity package bytes changed after receipt creation."
        }
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($reviewPath) -and (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
            Remove-Item -LiteralPath $reviewPath -Force
        }
        throw "BodyRig checkout/package authority changed after high-fidelity human review write; removed non-authoritative receipt '$reviewPath'. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity human review: PASS | body=$([string]$result.body_id)"
Write-Host "Package SHA: $([string]$result.package_sha256)"
Write-Host "Receipt: $reviewPath"
Write-Host "Authority: package SHA + component-state SHA + bodyrig-high-fidelity-human-review-v1 | production_activation=false"
exit 0
