param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig anatomy-promotion path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig anatomy-promotion path."
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
        throw "BodyRig checkout revision changed while anatomy promotion was being materialized; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout changed while anatomy promotion was being materialized; checkout is dirty." }
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
    throw "Could not verify Python runtime for BodyRig anatomy promotion."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig anatomy promotion requires Python 3.11+; detected $versionText."
}

$previousPythonPath = $env:PYTHONPATH
$packagePath = ""
$receiptPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.high_fidelity_anatomy_promotion_cli `
            --preview-job-id $PreviewJobId `
            --bodyrig-revision $initialHead)
        if ($LASTEXITCODE -ne 0) {
            throw "Anatomy-promotion CLI failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json -Depth 20 }
    catch { throw "Anatomy-promotion CLI did not return canonical JSON." }
    if ($result.ok -ne $true) { throw "Anatomy-promotion CLI did not report PASS." }
    if ([string]$result.preview_job_id -ne $PreviewJobId) { throw "Anatomy-promotion CLI returned a different preview job id." }
    if ([string]$result.bodyrig_revision -ne $initialHead) { throw "Anatomy-promotion CLI returned a different BodyRig revision." }
    if ([string]$result.source_package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Anatomy-promotion CLI returned an invalid source package SHA." }
    if ([string]$result.component_review_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Anatomy-promotion CLI returned an invalid component-review SHA." }
    if ([string]$result.promoted_package_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Anatomy-promotion CLI returned an invalid promoted package SHA." }
    if ([string]$result.promoted_avatar_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Anatomy-promotion CLI returned an invalid promoted avatar SHA." }
    if ([string]$result.promotion_component -ne "body_anatomy") { throw "Anatomy-promotion CLI crossed the component boundary." }
    if ([string]$result.components_after.body_anatomy -ne "complete") { throw "Promoted package did not make body_anatomy complete." }
    if ($result.production_activation -ne $false) { throw "Anatomy promotion must remain independently non-activating." }
    $packagePath = [string]$result.package_path
    $receiptPath = [string]$result.receipt_path
    if ([string]::IsNullOrWhiteSpace($packagePath) -or -not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
        throw "Anatomy-promotion package was not persisted at the returned path."
    }
    if ([string]::IsNullOrWhiteSpace($receiptPath) -or -not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "Anatomy-promotion receipt was not persisted at the returned path."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($receiptPath) -and (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            Remove-Item -LiteralPath $receiptPath -Force
        }
        if (-not [string]::IsNullOrWhiteSpace($packagePath) -and (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
            Remove-Item -LiteralPath $packagePath -Force
        }
        throw "BodyRig checkout authority changed after anatomy promotion; removed newly materialized promotion artifacts. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig anatomy promotion: PASS | preview=$PreviewJobId"
Write-Host "Package: $packagePath"
Write-Host "Receipt: $receiptPath"
Write-Host "body_anatomy: complete"
Write-Host "Hair/eyes/face-secondary: unchanged from reviewed candidate"
Write-Host "Authority: exact component review + exact source candidate + clean exact checkout | production_activation=false"
exit 0
