param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$IdentityWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$BodyRigPython = "",
    [string]$UnityExe = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe",
    [switch]$SkipBuild,
    [switch]$OpenPreview
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
    return (Get-FileHash -LiteralPath (Need-File -Path $Path -Label "Hash input") -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig retained face-quality preview is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Retained face-quality preview must run from canonical main."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Retained face-quality preview requires an exact clean BodyRig checkout."
}

$PackagePath = Need-File -Path $PackagePath -Label "Retained candidate package"
$IdentityWorkspace = Need-Directory -Path $IdentityWorkspace -Label "Retained identity workspace"
$packageSha = Sha256 $PackagePath

$hairEyeScript = Need-File -Path (Join-Path $repoRoot "run-retained-hair-eye-preview.ps1") -Label "Retained hair+eye preview operator"
$faceScript = Need-File -Path (Join-Path $repoRoot "run-face-secondary-hair-eye-windows-preview.ps1") -Label "Face-secondary hair+eye preview operator"

$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Retained face-quality preview output already exists: $OutputRoot"
}
$parent = Split-Path -Parent $OutputRoot
if ([string]::IsNullOrWhiteSpace($parent)) { throw "OutputRoot must have a parent directory." }
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$attempt = Join-Path $parent ("." + [IO.Path]::GetFileName($OutputRoot) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $attempt | Out-Null
$committed = $false

try {
    $hairEyeRoot = Join-Path $attempt "hair-eye"
    $faceRoot = Join-Path $attempt "face-secondary"

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "BODYRIG RETAINED FACE QUALITY PREVIEW"
    Write-Host "Revision:          $head"
    Write-Host "Package SHA:       $packageSha"
    Write-Host "Reconstruction:    REUSED / NO SITH RERUN"
    Write-Host "Hair+eyes:         SOURCE-DERIVED REVIEW RUNTIME"
    Write-Host "Face secondary:    ROUNDED GEOMETRY REVIEW"
    Write-Host "Production:        FALSE"
    Write-Host "============================================================"

    $hairEyeArgs = @{
        PackagePath = $PackagePath
        IdentityWorkspace = $IdentityWorkspace
        OutputRoot = $hairEyeRoot
        Distribution = $Distribution
        InstallRoot = $InstallRoot
        WslExe = $WslExe
    }
    if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $hairEyeArgs.BodyRigPython = $BodyRigPython }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $hairEyeArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $hairEyeArgs.SkipBuild = $true }

    Write-Host ""
    Write-Host "=== 1/2 REBUILD REVIEW-ONLY HAIR + EYES FROM RETAINED RECONSTRUCTION ==="
    & $hairEyeScript @hairEyeArgs
    if ($LASTEXITCODE -ne 0) { throw "Retained hair+eye preview failed with exit code $LASTEXITCODE" }

    $hairEyeRuntime = Need-Directory -Path (Join-Path $hairEyeRoot "runtime") -Label "Retained hair+eye runtime"

    $faceArgs = @{
        PackagePath = $PackagePath
        HairEyeRuntimeDir = $hairEyeRuntime
        OutputDir = $faceRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $faceArgs.BodyRigPython = $BodyRigPython }
    if (-not [string]::IsNullOrWhiteSpace($UnityExe)) { $faceArgs.UnityExe = $UnityExe }
    if ($SkipBuild) { $faceArgs.SkipBuild = $true }

    Write-Host ""
    Write-Host "=== 2/2 COMPOSE ROUNDED FACE SECONDARY + WINDOWS PREVIEW ==="
    & $faceScript @faceArgs
    if ($LASTEXITCODE -ne 0) { throw "Face-secondary hair+eye preview failed with exit code $LASTEXITCODE" }

    $snapshots = Need-Directory -Path (Join-Path $faceRoot "windows-preview\snapshots") -Label "Face-quality snapshot directory"
    $required = @(
        "front-full.png",
        "three-quarter-full.png",
        "face-front.png",
        "face-zoom.png",
        "eyes-closeup.png",
        "mouth-open.png"
    )
    $snapshotHashes = [ordered]@{}
    foreach ($name in $required) {
        $path = Need-File -Path (Join-Path $snapshots $name) -Label "Face-quality snapshot $name"
        $snapshotHashes[$name] = Sha256 $path
    }

    $summary = [ordered]@{
        format = "bodyrig-retained-face-quality-preview"
        version = 1
        bodyrig_revision = $head
        package_sha256 = $packageSha
        reconstruction_rerun = $false
        source_hair_eye_runtime_rebuilt = $true
        rounded_face_secondary_geometry = $true
        mouth_geometry_revision = "deterministic-rounded-oval-cavity-v2"
        teeth_geometry_revision = "deterministic-individual-rounded-dental-row-v2"
        eyelash_geometry_revision = "deterministic-smplx-head-anchored-tapered-ribbon-v2"
        snapshots = $snapshotHashes
        comparison_only = $true
        human_visual_review_required = $true
        production_activation = $false
    }
    $summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $attempt "face-quality-preview.json") -Encoding UTF8

    if ((Sha256 $PackagePath) -ne $packageSha) { throw "Retained package bytes changed during face-quality preview." }
    Move-Item -LiteralPath $attempt -Destination $OutputRoot
    $committed = $true

    $finalSnapshots = Join-Path $OutputRoot "face-secondary\windows-preview\snapshots"
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "RETAINED FACE QUALITY PREVIEW: READY"
    Write-Host "Snapshots:        $finalSnapshots"
    Write-Host "Open first:       face-front.png / face-zoom.png / eyes-closeup.png / mouth-open.png"
    Write-Host "SiTH rerun:       FALSE"
    Write-Host "Human review:     REQUIRED"
    Write-Host "Production:       FALSE"
    Write-Host "============================================================"

    if ($OpenPreview) {
        Start-Process explorer.exe -ArgumentList @($finalSnapshots)
    }
    exit 0
}
finally {
    if (-not $committed -and (Test-Path -LiteralPath $attempt -PathType Container)) {
        Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue
    }
}
