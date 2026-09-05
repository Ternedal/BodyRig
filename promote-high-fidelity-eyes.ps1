param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [Parameter(Mandatory = $true)][string]$CandidatePackage,
    [Parameter(Mandatory = $true)][string]$TargetPackage,
    [Parameter(Mandatory = $true)][string]$BaseRuntimeDir,
    [Parameter(Mandatory = $true)][string]$IrisCandidateDir,
    [Parameter(Mandatory = $true)][string]$SourceEyeAppearanceDir,
    [Parameter(Mandatory = $true)][string]$ReviewedRuntimeDir,
    [Parameter(Mandatory = $true)][string]$EyeRuntimeDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig eye package promotion path is Windows-only."
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
    if ($dirty.Count -gt 0) { throw "Eye package promotion requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout changed during eye package promotion; expected $ExpectedHead, got $head."
    }
    return $head
}
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
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$CandidatePackage = Need-File -Path $CandidatePackage -Label "Reviewed source candidate package"
$TargetPackage = Need-File -Path $TargetPackage -Label "Promoted destination source package"
$BaseRuntimeDir = Need-Directory -Path $BaseRuntimeDir -Label "Combined source hair+eye runtime"
$IrisCandidateDir = Need-Directory -Path $IrisCandidateDir -Label "Reviewed iris candidate"
$SourceEyeAppearanceDir = Need-Directory -Path $SourceEyeAppearanceDir -Label "Source eye appearance"
$ReviewedRuntimeDir = Need-Directory -Path $ReviewedRuntimeDir -Label "Iris-reviewed runtime"
$EyeRuntimeDir = Need-Directory -Path $EyeRuntimeDir -Label "Fingerprint-matched eye-only runtime"
$bridgeScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_eye_review_runtime.py") -Label "Eye-only runtime bridge"
$bridgeScriptSha = Sha256 $bridgeScript

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$localPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $localPython -PathType Leaf) { (Resolve-Path -LiteralPath $localPython).Path } elseif ($null -ne $pythonCommand) { $pythonCommand.Source } else { throw "Python 3.11+ executable was not found." }
$versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python runtime." }
if ([version]$versionText -lt [version]"3.11") { throw "BodyRig eye promotion requires Python 3.11+; detected $versionText." }

$previousPythonPath = $env:PYTHONPATH
$promotionRoot = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot$([IO.Path]::PathSeparator)$previousPythonPath" }
    Push-Location $repoRoot
    try {
        $raw = @(& $python -m bodyrig.high_fidelity_eye_promotion_cli promote `
            --preview-job-id $PreviewJobId `
            --candidate-package $CandidatePackage `
            --target-package $TargetPackage `
            --base-runtime-dir $BaseRuntimeDir `
            --iris-candidate-dir $IrisCandidateDir `
            --source-eye-appearance-dir $SourceEyeAppearanceDir `
            --reviewed-runtime-dir $ReviewedRuntimeDir `
            --eye-runtime-dir $EyeRuntimeDir `
            --bridge-script-sha256 $bridgeScriptSha `
            --promotion-bodyrig-revision $head)
        if ($LASTEXITCODE -ne 0) { throw "Eye package promotion CLI failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $result = (($raw -join "`n").Trim() | ConvertFrom-Json -Depth 40) }
    catch { throw "Eye package promotion CLI returned unreadable JSON." }
    if ($result.ok -ne $true -or [string]$result.mode -ne "promote") { throw "Eye package promotion CLI did not report canonical PASS." }
    if ([string]$result.promoted_package_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.promoted_avatar_sha256 -notmatch '^[0-9a-f]{64}$' -or [string]$result.reviewed_eye_fingerprint_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Eye package promotion returned invalid authority hashes."
    }
    if ($result.source_hair_runtime_imported -ne $false -or $result.production_activation -ne $false) {
        throw "Eye package promotion crossed hair/production authority."
    }
    if (-not ($result.components_after.PSObject.Properties.Name -contains "eyes") -or [string]$result.components_after.eyes -ne "complete") {
        throw "Eye package promotion did not make only the eyes component complete."
    }
    $packagePath = [IO.Path]::GetFullPath([string]$result.package_path)
    $receiptPath = [IO.Path]::GetFullPath([string]$result.receipt_path)
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf) -or -not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "Eye package promotion did not persist canonical package/receipt outputs."
    }
    if ((Sha256 $packagePath) -ne [string]$result.promoted_package_sha256) { throw "Promoted package hash differs from CLI authority." }
    $promotionRoot = Split-Path -Parent $receiptPath

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
        if ((Sha256 $bridgeScript) -ne $bridgeScriptSha) { throw "Eye-only bridge bytes changed during package promotion." }
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($promotionRoot) -and (Test-Path -LiteralPath $promotionRoot -PathType Container)) {
            Remove-Item -LiteralPath $promotionRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "BodyRig authority changed after eye package creation; removed only the newly created eye promotion directory. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig high-fidelity eye package promotion: PASS"
Write-Host "Package:             $packagePath"
Write-Host "Receipt:             $receiptPath"
Write-Host "Revision:            $head"
Write-Host "Eyes:                COMPLETE"
Write-Host "Hair preserved:       $($result.hair_complete_preserved)"
Write-Host "Source hair imported: FALSE"
Write-Host "Production:           FALSE"
Write-Host "NEXT: remaining face-secondary authority + final high-fidelity review + Windows/Quest physical acceptance."
exit 0
