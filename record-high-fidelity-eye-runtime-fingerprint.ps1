param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [Parameter(Mandatory = $true)][string]$BaseRuntimeDir,
    [Parameter(Mandatory = $true)][string]$IrisCandidateDir,
    [Parameter(Mandatory = $true)][string]$SourceEyeAppearanceDir,
    [Parameter(Mandatory = $true)][string]$ReviewedRuntimeDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig eye runtime fingerprint path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "Eye runtime fingerprint recording requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during eye runtime fingerprint recording; expected $ExpectedHead, got $head."
    }
    return $head
}

function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$baseRoot = Need-Directory -Path $BaseRuntimeDir -Label "Combined source hair+eye runtime"
$irisRoot = Need-Directory -Path $IrisCandidateDir -Label "Reviewed iris candidate"
$sourceRoot = Need-Directory -Path $SourceEyeAppearanceDir -Label "Source eye appearance"
$reviewedRoot = Need-Directory -Path $ReviewedRuntimeDir -Label "Iris-reviewed runtime"
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { throw "Python 3.11+ executable 'python' was not found." }
$python = $pythonCommand.Source
$versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python runtime." }
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) { throw "BodyRig eye runtime fingerprint requires Python 3.11+; detected $versionText." }

$previousPythonPath = $env:PYTHONPATH
$receiptPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.high_fidelity_eye_runtime_fingerprint_cli record `
            --preview-job-id $PreviewJobId `
            --base-runtime-dir $baseRoot `
            --iris-candidate-dir $irisRoot `
            --source-eye-appearance-dir $sourceRoot `
            --reviewed-runtime-dir $reviewedRoot `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw "Eye runtime fingerprint CLI failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 40) }
    catch { throw "Eye runtime fingerprint CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "record") { throw "Eye runtime fingerprint CLI did not report canonical PASS." }
    if ([string]$result.fingerprint_bodyrig_revision -ne $head) { throw "Eye runtime fingerprint was recorded by a different BodyRig revision." }
    if ([string]$result.candidate_package_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.review_vrm_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.fingerprint_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Eye runtime fingerprint returned invalid authority hashes."
    }
    if ($result.index_independent -ne $true -or $result.buffer_offset_independent -ne $true -or $result.eyes_promotion_eligibility_verified -ne $true) {
        throw "Eye runtime fingerprint did not preserve canonical semantic/index-independent authority."
    }
    if ($result.eye_component_authority -ne $false -or $result.package_mutation_performed -ne $false -or $result.eyes_promoted -ne $false -or $result.production_activation -ne $false) {
        throw "Eye runtime fingerprint crossed component/package/production authority."
    }
    $receiptPath = [IO.Path]::GetFullPath([string]$result.fingerprint_path)
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "Eye runtime fingerprint receipt was not persisted." }

    try { [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head) }
    catch {
        if (-not [string]::IsNullOrWhiteSpace($receiptPath) -and (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig checkout changed after eye fingerprint creation; removed only the newly created fingerprint receipt. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity eye runtime fingerprint: PASS"
Write-Host "Receipt:             $receiptPath"
Write-Host "Revision:            $head"
Write-Host "Semantic fingerprint: VERIFIED"
Write-Host "glTF indices:         IGNORED"
Write-Host "Buffer offsets:       IGNORED"
Write-Host "Eye authority:        FALSE"
Write-Host "Package mutated:      FALSE"
Write-Host "Eyes promoted:        FALSE"
Write-Host "Production:           FALSE"
Write-Host "NEXT: rebuild an eye-only runtime and require this exact semantic fingerprint before any package materialization."
exit 0
