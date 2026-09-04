param(
    [Parameter(Mandatory = $true)][string]$BaseRuntimeDir,
    [Parameter(Mandatory = $true)][string]$IrisCandidateDir,
    [Parameter(Mandatory = $true)][string]$SourceEyeAppearanceDir,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig reviewed iris runtime path is Windows-only."
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
    if ($dirty.Count -gt 0) { throw "Reviewed iris runtime requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during reviewed iris runtime build; expected $ExpectedHead, got $head."
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
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Reviewed iris runtime output already exists: $OutputDir" }

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) { throw "Python 3.11+ executable 'python' was not found." }
$python = $pythonCommand.Source
$versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python runtime." }
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) { throw "BodyRig reviewed iris runtime requires Python 3.11+; detected $versionText." }

$previousPythonPath = $env:PYTHONPATH
$created = $false
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.source_iris_review_runtime_cli build `
            --base-runtime-dir $baseRoot `
            --iris-candidate-dir $irisRoot `
            --source-eye-appearance-dir $sourceRoot `
            --reviewed-runtime-dir $OutputDir `
            --bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw "Reviewed iris runtime CLI failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 20) }
    catch { throw "Reviewed iris runtime CLI returned unreadable JSON." }
    $created = Test-Path -LiteralPath $OutputDir -PathType Container
    if ($result.ok -ne $true -or [string]$result.mode -ne "build") { throw "Reviewed iris runtime CLI did not report canonical PASS." }
    if ([string]$result.bodyrig_revision -ne $head) { throw "Reviewed iris runtime was created by a different BodyRig revision." }
    if ([string]$result.base_review_vrm_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.reviewed_vrm_sha256 -ne [string]$result.base_review_vrm_sha256) {
        throw "Reviewed iris runtime did not preserve exact base VRM bytes."
    }
    if ($result.runtime_bytes_unchanged -ne $true -or $result.source_eye_pixels_unchanged -ne $true) {
        throw "Reviewed iris runtime did not prove unchanged runtime/source-eye pixels."
    }
    if ($result.iris_identity_isolated -ne $true -or [string]$result.iris_appearance_status -ne "source-isolated-review-pass") {
        throw "Reviewed iris runtime did not carry passed iris-isolation authority."
    }
    if ($result.eyes_promotion_eligible -ne $false -or $result.eye_component_authority -ne $false -or $result.production_activation -ne $false) {
        throw "Reviewed iris runtime crossed eye-component/promotion/production authority."
    }
    foreach ($path in @([string]$result.reviewed_vrm_path,[string]$result.review_receipt_path)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Reviewed iris runtime artifact missing: $path" }
        if ((Split-Path -Parent ([IO.Path]::GetFullPath($path))) -ne $OutputDir) { throw "Reviewed iris runtime artifact escaped the output directory." }
    }

    try { [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head) }
    catch {
        if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
            Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig checkout changed after reviewed iris runtime creation; removed only the newly created reviewed-runtime directory. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig source iris reviewed runtime: READY"
Write-Host "Output:             $OutputDir"
Write-Host "Revision:           $head"
Write-Host "VRM bytes:          UNCHANGED"
Write-Host "Source eye pixels:  UNCHANGED"
Write-Host "Iris isolation:     SOURCE-ISOLATED REVIEW PASS"
Write-Host "Eyes promotion:     FALSE"
Write-Host "Eye authority:      FALSE"
Write-Host "Production:         FALSE"
Write-Host "NEXT: use this sidecar-bound runtime for explicit eye/face review; it does not make eyes complete."
exit 0
