param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$RuntimeDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Face-secondary Windows preview is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
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
function Invoke-JsonPython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& $BodyRigPython @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
        throw "$Label failed: $($raw -join [Environment]::NewLine)"
    }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "$Label returned unreadable JSON." }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$PackagePath = Need-File -Path $PackagePath -Label "Promoted source package"
$RuntimeDir = Need-Directory -Path $RuntimeDir -Label "Face-secondary review runtime"
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Face-secondary preview output already exists; refusing cross-attempt reuse: $OutputDir"
}
$currentHeadRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $currentHeadRaw.Count -ne 1 -or ([string]$currentHeadRaw[0]) -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig HEAD."
}
$currentHead = ([string]$currentHeadRaw[0]).ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Face-secondary preview requires an exact clean BodyRig checkout."
}

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $BodyRigPython = $venvPython }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$parent = Split-Path -Parent $OutputDir
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "Face-secondary preview output parent does not exist: $parent"
}
$attempt = Join-Path $parent (".bodyrig-face-secondary-preview-" + [Guid]::NewGuid().ToString("N"))
$prepDir = Join-Path $attempt "preparation"
$renderDir = Join-Path $attempt "render"
$committed = $false

try {
    New-Item -ItemType Directory -Path $attempt | Out-Null
    $prepared = Invoke-JsonPython -Label "Face-secondary preview preparation" -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_preview_cli", "prepare",
        "--package", $PackagePath,
        "--runtime-dir", $RuntimeDir,
        "--output-dir", $prepDir,
        "--bodyrig-revision", $currentHead
    )
    $comparisonPackage = Need-File -Path ([string]$prepared.comparisonPackagePath) -Label "Face-secondary comparison package"

    $renderArgs = @{
        PackagePath = $comparisonPackage
        OutputDir = $renderDir
        BodyRigPython = $BodyRigPython
    }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $renderArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $renderArgs.SkipBuild = $true }
    & (Join-Path $repoRoot "run-fidelity-windows-render-probe.ps1") @renderArgs
    if ($LASTEXITCODE -ne 0) { throw "Face-secondary Windows renderer probe failed with exit code $LASTEXITCODE" }

    [void](Invoke-JsonPython -Label "Face-secondary preview finalization" -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_preview_cli", "finalize",
        "--preparation-dir", $prepDir,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $renderDir
    ))

    $headAfterRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
    $dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headAfterRaw.Count -ne 1 -or ([string]$headAfterRaw[0]).ToLowerInvariant() -ne $currentHead -or $dirtyAfter.Count -gt 0) {
        throw "BodyRig checkout changed during face-secondary preview; refusing stale evidence."
    }

    Move-Item -LiteralPath $attempt -Destination $OutputDir
    $finalPrep = Join-Path $OutputDir "preparation"
    $finalRender = Join-Path $OutputDir "render"
    [void](Invoke-JsonPython -Label "Face-secondary preview post-commit verification" -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_preview_cli", "verify",
        "--preparation-dir", $finalPrep,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $finalRender
    ))
    $committed = $true
} finally {
    if (-not $committed) {
        if (Test-Path -LiteralPath $attempt -PathType Container) { Remove-Item -LiteralPath $attempt -Recurse -Force }
        if (Test-Path -LiteralPath $OutputDir -PathType Container) { Remove-Item -LiteralPath $OutputDir -Recurse -Force }
    }
}

Write-Host "BodyRig face-secondary Windows preview: PASS"
Write-Host "Output: $OutputDir"
Write-Host "Views: canonical v1 + face-zoom + eyes-closeup + mouth-open"
Write-Host "Authority: comparison-only; human review still required; no package/production activation"
exit 0
