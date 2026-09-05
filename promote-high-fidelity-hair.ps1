param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^hfpreview-[0-9a-f]{32}$')]
    [string]$PreviewJobId,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig hair-promotion path is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig hair-promotion path."
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
        throw "BodyRig checkout revision changed during hair promotion; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "Hair promotion requires an exact clean BodyRig checkout." }
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

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python 3.11+ executable 'python' was not found. Run from the validated BodyRig operator environment."
}
$pythonExe = $pythonCommand.Source
$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') {
    throw "Could not verify Python runtime for BodyRig hair promotion."
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "BodyRig hair promotion requires Python 3.11+; detected $versionText."
}

$previousPythonPath = $env:PYTHONPATH
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-hair-promotion-" + [Guid]::NewGuid().ToString("N"))
$hairRuntimeDir = Join-Path $tempRoot "hair-runtime"
$promotionRoot = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    New-Item -ItemType Directory -Path $tempRoot | Out-Null

    Push-Location $repoRoot
    try {
        $prepareOutput = @(& $pythonExe -m bodyrig.high_fidelity_hair_promotion_cli prepare --preview-job-id $PreviewJobId)
        if ($LASTEXITCODE -ne 0) { throw "Hair-promotion prepare failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $prepared = (($prepareOutput -join "`n").Trim() | ConvertFrom-Json -Depth 30) }
    catch { throw "Hair-promotion prepare did not return canonical JSON." }
    if ($prepared.ok -ne $true -or [string]$prepared.preview_job_id -ne $PreviewJobId) {
        throw "Hair-promotion prepare did not bind the requested preview."
    }
    if ([string]$prepared.source_bodyrig_revision -notmatch '^[0-9a-f]{40}$') {
        throw "Hair-promotion prepare returned invalid source BodyRig revision."
    }
    if ([string]$prepared.expected_hair_review_bridge_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Hair-promotion prepare returned invalid reviewed hair bridge SHA."
    }
    if ($prepared.production_activation -ne $false) {
        throw "Hair-promotion prepare crossed the production authority boundary."
    }

    $candidatePackage = Need-File -Path ([string]$prepared.source_candidate_package) -Label "Exact reviewed anatomy candidate package"
    $hairCandidateDir = Need-Directory -Path ([string]$prepared.hair_candidate_dir) -Label "Exact source hair candidate"
    $candidateWorkspace = Need-Directory -Path ([string]$prepared.candidate_workspace) -Label "Exact anatomy candidate workspace"
    [void](Need-File -Path ([string]$prepared.anatomy_promoted_package) -Label "Exact anatomy-promoted package")
    [void](Need-File -Path ([string]$prepared.anatomy_promotion_receipt) -Label "Exact anatomy-promotion receipt")

    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    $hairBuilder = Need-File -Path (Join-Path $repoRoot "build-source-hair-review-runtime.ps1") -Label "Canonical source-hair runtime builder"
    $builderArgs = @{
        PackagePath = $candidatePackage
        CandidateDir = $hairCandidateDir
        CandidateWorkspace = $candidateWorkspace
        OutputDir = $hairRuntimeDir
        Distribution = $Distribution
        InstallRoot = $InstallRoot
        WslExe = $WslExe
    }
    & $hairBuilder @builderArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical source-hair runtime reconstruction failed with exit code $LASTEXITCODE."
    }
    [void](Need-File -Path (Join-Path $hairRuntimeDir "source-hair-review.vrm") -Label "Rebuilt hair-only review VRM")
    [void](Need-File -Path (Join-Path $hairRuntimeDir "source-hair-review-bridge.json") -Label "Rebuilt hair bridge result")
    [void](Need-File -Path (Join-Path $hairRuntimeDir "source-hair-review-runtime.json") -Label "Rebuilt hair runtime receipt")
    [void](Need-File -Path (Join-Path $hairRuntimeDir "source-hair-body-binding.json") -Label "Rebuilt hair/body binding")
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)

    Push-Location $repoRoot
    try {
        $promoteOutput = @(& $pythonExe -m bodyrig.high_fidelity_hair_promotion_cli promote `
            --preview-job-id $PreviewJobId `
            --promotion-bodyrig-revision $initialHead `
            --hair-runtime-dir $hairRuntimeDir)
        if ($LASTEXITCODE -ne 0) { throw "Hair-promotion materialization failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    try { $result = (($promoteOutput -join "`n").Trim() | ConvertFrom-Json -Depth 30) }
    catch { throw "Hair-promotion materialization did not return canonical JSON." }
    if ($result.ok -ne $true) { throw "Hair-promotion materialization did not report PASS." }
    if ([string]$result.preview_job_id -ne $PreviewJobId) { throw "Hair promotion returned a different preview id." }
    if ([string]$result.promotion_bodyrig_revision -ne $initialHead) { throw "Hair promotion returned a different promotion revision." }
    if ([string]$result.expected_hair_review_bridge_sha256 -ne [string]$result.rebuilt_hair_bridge_canonical_sha256) {
        throw "Rebuilt hair-only bridge does not match the exact physically reviewed hair stage."
    }
    if ([string]$result.components_after.body_anatomy -ne "complete" -or [string]$result.components_after.hair -ne "complete") {
        throw "Hair promotion did not preserve anatomy complete and make hair complete."
    }
    if ($result.eyes_imported -ne $false) { throw "Hair promotion illegally imported eye review runtime." }
    if ($result.production_activation -ne $false) { throw "Hair promotion crossed the production authority boundary." }
    $promotionRoot = [string]$result.promotion_root
    if ([string]::IsNullOrWhiteSpace($promotionRoot) -or -not (Test-Path -LiteralPath $promotionRoot -PathType Container)) {
        throw "Hair promotion evidence root was not persisted."
    }
    [void](Need-File -Path ([string]$result.package_path) -Label "Hair-promoted package")
    [void](Need-File -Path ([string]$result.receipt_path) -Label "Hair-promotion receipt")

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($promotionRoot) -and (Test-Path -LiteralPath $promotionRoot -PathType Container)) {
            Remove-Item -LiteralPath $promotionRoot -Recurse -Force
        }
        throw "BodyRig checkout authority changed after hair promotion; removed newly materialized hair-promotion authority. $($_.Exception.Message)"
    }

    Write-Host ""
    Write-Host "BodyRig hair promotion: PASS | preview=$PreviewJobId"
    Write-Host "Source revision:    $([string]$result.source_bodyrig_revision)"
    Write-Host "Promotion revision: $([string]$result.promotion_bodyrig_revision)"
    Write-Host "Reviewed hair hash: $([string]$result.expected_hair_review_bridge_sha256)"
    Write-Host "Rebuilt hair hash:  $([string]$result.rebuilt_hair_bridge_canonical_sha256)"
    Write-Host "Package:             $([string]$result.package_path)"
    Write-Host "body_anatomy: complete"
    Write-Host "hair:         complete"
    Write-Host "eyes:         unchanged / no eye review runtime imported"
    Write-Host "Production:   FALSE"
    exit 0
} finally {
    $env:PYTHONPATH = $previousPythonPath
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
