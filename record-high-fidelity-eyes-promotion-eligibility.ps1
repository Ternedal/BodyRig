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
    throw "The canonical BodyRig eyes promotion-eligibility path is Windows-only."
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
    if ($dirty.Count -gt 0) { throw "Eyes promotion eligibility requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during eyes promotion-eligibility recording; expected $ExpectedHead, got $head."
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
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) { throw "BodyRig eyes promotion eligibility requires Python 3.11+; detected $versionText." }

$previousPythonPath = $env:PYTHONPATH
$receiptPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.high_fidelity_eyes_promotion_eligibility_cli record `
            --preview-job-id $PreviewJobId `
            --base-runtime-dir $baseRoot `
            --iris-candidate-dir $irisRoot `
            --source-eye-appearance-dir $sourceRoot `
            --reviewed-runtime-dir $reviewedRoot `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw "Eyes promotion-eligibility CLI failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 20) }
    catch { throw "Eyes promotion-eligibility CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "record") { throw "Eyes promotion-eligibility CLI did not report canonical PASS." }
    if ([string]$result.bodyrig_revision -ne $head) { throw "Eyes promotion eligibility was recorded by a different BodyRig revision." }
    if ([string]$result.candidate_package_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.review_vrm_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.iris_review_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Eyes promotion eligibility returned invalid authority hashes."
    }
    if ($result.eyes_promotion_eligible -ne $true) { throw "Eyes did not become promotion-eligible after exact visual + iris authority composition." }
    if ($result.eye_component_authority -ne $false -or $result.package_mutation_performed -ne $false -or $result.eyes_promoted -ne $false -or $result.production_activation -ne $false) {
        throw "Eyes promotion eligibility crossed component/package/production authority."
    }
    if ([string]$result.eyelash_status -ne "missing") { throw "Eyes eligibility must not hide the separate missing face-secondary eyelash blocker." }
    $receiptPath = [IO.Path]::GetFullPath([string]$result.eligibility_path)
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "Eyes promotion-eligibility receipt was not persisted." }

    try { [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head) }
    catch {
        if (-not [string]::IsNullOrWhiteSpace($receiptPath) -and (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig checkout changed after eyes eligibility creation; removed only the newly created eligibility receipt. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity eyes promotion eligibility: PASS"
Write-Host "Receipt:            $receiptPath"
Write-Host "Revision:           $head"
Write-Host "Eyes eligible:       TRUE"
Write-Host "Eye authority:       FALSE"
Write-Host "Package mutated:     FALSE"
Write-Host "Eyes promoted:       FALSE"
Write-Host "Eyelashes:           MISSING (face_secondary blocker)"
Write-Host "Production:          FALSE"
Write-Host "NEXT: materialize the exact reviewed eye runtime into a new candidate package; eligibility alone never mutates the source package."
exit 0
