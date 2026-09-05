param(
    [Parameter(Mandatory = $true)][string]$PreparationDir,
    [Parameter(Mandatory = $true)][string]$RuntimeDir,
    [Parameter(Mandatory = $true)][string]$RenderDir,
    [Parameter(Mandatory = $true)][string]$HumanReviewDir,
    [Parameter(Mandatory = $true)][string]$SourcePackage,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Face-secondary promotion is Windows-only." }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

function Need-Path {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label,[switch]$Directory)
    if ($Directory) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    } else {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Invoke-BodyRigJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments,[Parameter(Mandatory = $true)][string]$Label)
    $raw = @(& $BodyRigPython @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) { throw "$Label failed: $($raw -join [Environment]::NewLine)" }
    try { return ([string]$raw[0]) | ConvertFrom-Json }
    catch { throw "$Label returned unreadable JSON." }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$PreparationDir = Need-Path -Path $PreparationDir -Label "Face-secondary preview preparation" -Directory
$RuntimeDir = Need-Path -Path $RuntimeDir -Label "Face-secondary review runtime" -Directory
$RenderDir = Need-Path -Path $RenderDir -Label "Face-secondary Windows render evidence" -Directory
$HumanReviewDir = Need-Path -Path $HumanReviewDir -Label "Face-secondary human review" -Directory
$SourcePackage = Need-Path -Path $SourcePackage -Label "Source promoted package"
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Face-secondary promotion output already exists; refusing overwrite: $OutputDir" }

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1 -or ([string]$headRaw[0]) -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve exact BodyRig HEAD." }
$head = ([string]$headRaw[0]).ToLowerInvariant()
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Face-secondary promotion requires an exact clean BodyRig checkout." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-Path -Path $BodyRigPython -Label "BodyRig Python"
$created = $false

try {
    $result = Invoke-BodyRigJson -Label "Face-secondary package promotion" -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_promotion_cli", "promote",
        "--preparation-dir", $PreparationDir,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $RenderDir,
        "--human-review-dir", $HumanReviewDir,
        "--source-package", $SourcePackage,
        "--output-dir", $OutputDir,
        "--bodyrig-revision", $head
    )
    $created = $true

    $headAfterRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
    $dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headAfterRaw.Count -ne 1 -or ([string]$headAfterRaw[0]).ToLowerInvariant() -ne $head -or $dirtyAfter.Count -gt 0) {
        throw "BodyRig checkout changed during face-secondary promotion; refusing stale package authority."
    }

    $verified = Invoke-BodyRigJson -Label "Face-secondary promotion post-write verification" -Arguments @(
        "-m", "bodyrig.high_fidelity_face_secondary_promotion_cli", "verify",
        "--preparation-dir", $PreparationDir,
        "--runtime-dir", $RuntimeDir,
        "--render-dir", $RenderDir,
        "--human-review-dir", $HumanReviewDir,
        "--source-package", $SourcePackage,
        "--output-dir", $OutputDir
    )
    if ([string]$verified.promotedPackagePath -ne [string]$result.promotedPackagePath) { throw "Face-secondary promotion path changed after verification." }
} catch {
    if ($created -and (Test-Path -LiteralPath $OutputDir -PathType Container)) { Remove-Item -LiteralPath $OutputDir -Recurse -Force }
    throw
}

Write-Host "BodyRig face-secondary promotion: PASS"
Write-Host "Package: $([string]$verified.promotedPackagePath)"
Write-Host "Face secondary: all five nested components complete; top-level derived complete"
Write-Host "Teeth: generic reviewed secondary anatomy; no source dental identity claimed"
Write-Host "Production: FALSE; final renderer/human/Quest acceptance remains separate"
exit 0
