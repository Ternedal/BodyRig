param(
    [Parameter(Mandatory = $true)][string]$CandidateDir,
    [Parameter(Mandatory = $true)][string]$SourceEyeAppearanceDir,
    [Parameter(Mandatory = $true)][switch]$ConfirmIrisIsolationChecklist,
    [Parameter(Mandatory = $true)][ValidateLength(1, 4000)][string]$QualityNote
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig iris-isolation review path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if (-not $ConfirmIrisIsolationChecklist) {
    throw "Iris isolation review requires explicit -ConfirmIrisIsolationChecklist after reviewing both exact source eye crops, both iris boundaries, pupil exclusion, sclera exclusion and bilateral consistency."
}
if ([string]::IsNullOrWhiteSpace($QualityNote)) { throw "QualityNote must contain the operator's iris-isolation review." }
$QualityNote = $QualityNote.Trim()

function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "Iris isolation review requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during iris isolation review; expected $ExpectedHead, got $head."
    }
    return $head
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$candidateRoot = (Resolve-Path -LiteralPath $CandidateDir).Path
$sourceRoot = (Resolve-Path -LiteralPath $SourceEyeAppearanceDir).Path
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { throw "Python 3.11+ executable 'python' was not found." }
$python = $pythonCommand.Source
$versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python runtime." }
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) { throw "BodyRig iris isolation review requires Python 3.11+; detected $versionText." }

$previousPythonPath = $env:PYTHONPATH
$reviewPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.source_iris_isolation_cli review `
            --candidate-dir $candidateRoot `
            --source-eye-appearance-dir $sourceRoot `
            --bodyrig-revision $head `
            --confirm-iris-isolation-checklist `
            --quality-note $QualityNote)
        if ($LASTEXITCODE -ne 0) { throw "Iris isolation review CLI failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }

    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 20) }
    catch { throw "Iris isolation review CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "review") { throw "Iris isolation review CLI did not report canonical PASS." }
    if ([string]$result.bodyrig_revision -ne $head) { throw "Iris review was produced by a different BodyRig revision." }
    if ($result.iris_identity_isolated -ne $true -or [string]$result.iris_appearance_status -ne "source-isolated-review-pass") {
        throw "Iris review did not grant the expected narrow isolation authority."
    }
    if ($result.eyes_promotion_eligible -ne $false -or $result.eye_component_authority -ne $false -or $result.production_activation -ne $false) {
        throw "Iris review crossed eye-component/promotion/production authority."
    }

    $reviewPath = [IO.Path]::GetFullPath([string]$result.review_path)
    if (-not (Test-Path -LiteralPath $reviewPath -PathType Leaf)) { throw "Iris review receipt was not persisted at the returned path." }
    if ((Split-Path -Parent $reviewPath) -ne $candidateRoot) { throw "Iris review receipt escaped the exact candidate directory." }

    try { [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head) }
    catch {
        if (-not [string]::IsNullOrWhiteSpace($reviewPath) -and (Test-Path -LiteralPath $reviewPath -PathType Leaf)) {
            Remove-Item -LiteralPath $reviewPath -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig checkout changed after iris review creation; removed only the newly created review receipt. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig source iris isolation review: PASS"
Write-Host "Receipt:          $reviewPath"
Write-Host "Revision:         $head"
Write-Host "Iris isolation:   SOURCE-ISOLATED REVIEW PASS"
Write-Host "Eyes promotion:   FALSE"
Write-Host "Eye authority:    FALSE"
Write-Host "Production:       FALSE"
Write-Host "NEXT: iris isolation may feed a separate eye-runtime/materialization review; this receipt alone never makes eyes complete."
exit 0
