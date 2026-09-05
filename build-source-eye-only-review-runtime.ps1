param(
    [Parameter(Mandatory = $true)][ValidatePattern('^hfpreview-[0-9a-f]{32}$')][string]$PreviewJobId,
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$BaseRuntimeDir,
    [Parameter(Mandatory = $true)][string]$IrisCandidateDir,
    [Parameter(Mandatory = $true)][string]$EyeGeometryDir,
    [Parameter(Mandatory = $true)][string]$EyeAppearanceDir,
    [Parameter(Mandatory = $true)][string]$ReviewedRuntimeDir,
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
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
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $lines = @(& $WslExe -d $Distribution -- @Arguments 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Lines = $lines; Text = ($lines -join "`n").Trim() }
}
function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $escaped = $Path.Replace('\', '\\')
    $result = Invoke-WslRaw -Arguments @("wslpath", "-a", "-u", $escaped)
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Text)) {
        throw "WSL path translation failed for $Path`: $($result.Text)"
    }
    return $result.Text.Trim()
}
function Resolve-BodyRigPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $local = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "BodyRig Python was not found." }
    return $command.Source
}
function Invoke-BodyRigPython {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $prior = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($prior)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$prior" })
        $lines = @(& $Python @Arguments 2>&1)
        $code = $LASTEXITCODE
        foreach ($line in $lines) { Write-Host ([string]$line) }
        if ($code -ne 0) { throw "$Label failed with exit code $code." }
        return (($lines -join "`n").Trim())
    } finally {
        $env:PYTHONPATH = $prior
    }
}
function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Eye-only runtime rebuild requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig HEAD changed during eye-only runtime rebuild."
    }
    return $head
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig eye-only runtime rebuild is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$PackagePath = Need-File -Path $PackagePath -Label "Reviewed candidate body package"
$BaseRuntimeDir = Need-Directory -Path $BaseRuntimeDir -Label "Combined source hair+eye runtime"
$IrisCandidateDir = Need-Directory -Path $IrisCandidateDir -Label "Reviewed iris candidate"
$EyeGeometryDir = Need-Directory -Path $EyeGeometryDir -Label "Eye geometry candidate directory"
$EyeAppearanceDir = Need-Directory -Path $EyeAppearanceDir -Label "Eye appearance/source directory"
$ReviewedRuntimeDir = Need-Directory -Path $ReviewedRuntimeDir -Label "Iris-reviewed runtime"
$CandidateWorkspace = Need-Directory -Path $CandidateWorkspace -Label "Anatomy candidate workspace"
$bridgeScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_eye_review_runtime.py") -Label "Eye-only review bridge"
$bridgeScriptSha = Sha256 $bridgeScript

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Eye-only rebuild output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Eye-only rebuild output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$partial = Join-Path $outputParent ("." + [IO.Path]::GetFileName($OutputDir) + ".partial-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $partial | Out-Null
$committed = $false

try {
    $python = Resolve-BodyRigPython -RepoRoot $repoRoot
    $versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$versionText -lt [version]"3.11") { throw "BodyRig Python 3.11+ is required; found $versionText." }

    $prepareRaw = Invoke-BodyRigPython -Python $python -RepoRoot $repoRoot -Label "Prepare eye-only runtime rebuild" -Arguments @(
        "-m", "bodyrig.high_fidelity_eye_runtime_rebuild_cli", "prepare",
        "--preview-job-id", $PreviewJobId,
        "--package", $PackagePath,
        "--base-runtime-dir", $BaseRuntimeDir,
        "--iris-candidate-dir", $IrisCandidateDir,
        "--source-eye-appearance-dir", $EyeAppearanceDir,
        "--reviewed-runtime-dir", $ReviewedRuntimeDir,
        "--staging-dir", $partial,
        "--bodyrig-revision", $head
    )
    try { $prepared = $prepareRaw | ConvertFrom-Json -Depth 30 }
    catch { throw "Eye-only rebuild prepare CLI returned unreadable JSON." }
    if ($prepared.ok -ne $true -or [string]$prepared.mode -ne "prepare" -or [string]$prepared.bodyrig_revision -ne $head) {
        throw "Eye-only rebuild preparation did not bind the exact checkout."
    }
    $avatarPath = Need-File -Path ([string]$prepared.base_avatar_path) -Label "Prepared exact base avatar"
    if ([string]$prepared.base_avatar_vrm_sha256 -ne (Sha256 $avatarPath)) { throw "Prepared base-avatar hash is inconsistent." }

    $wslCommand = Get-Command $WslExe -ErrorAction SilentlyContinue
    if ($null -eq $wslCommand) { throw "WSL executable not found: $WslExe" }
    $WslExe = $wslCommand.Source
    if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        $home = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
        if ($home.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($home.Text)) { throw "Could not resolve WSL home directory: $($home.Text)" }
        $InstallRoot = "$($home.Text.Trim())/.local/share/bodyrig/sith"
    }
    if (-not $InstallRoot.StartsWith("/")) { throw "-InstallRoot must be an absolute Linux path." }
    $InstallRoot = $InstallRoot.TrimEnd("/")
    $venvPython = "$InstallRoot/.bodyrig-venv/bin/python"
    $modelDir = "$InstallRoot/data/body_models/smplx"
    $uvObj = "$InstallRoot/data/smplx_uv.obj"
    foreach ($probePath in @(
        $venvPython,
        "$modelDir/SMPLX_NEUTRAL.npz",
        "$modelDir/SMPLX_MALE.npz",
        "$modelDir/SMPLX_FEMALE.npz",
        $uvObj
    )) {
        $flag = $(if ($probePath -eq $venvPython) { "-x" } else { "-f" })
        $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", $flag, $probePath)
        if ($probe.ExitCode -ne 0) { throw "Required SiTH/SMPL-X runtime artifact missing: $probePath" }
    }
    $cudaProbe = Invoke-WslRaw -Arguments @(
        $venvPython, "-c", "import torch,smplx,numpy; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
    )
    if ($cudaProbe.ExitCode -ne 0) { throw "SiTH eye-only CUDA/runtime probe failed: $($cudaProbe.Text)" }

    $avatarWsl = Convert-WindowsPathToWsl -Path $avatarPath
    $workspaceWsl = Convert-WindowsPathToWsl -Path $CandidateWorkspace
    $eyeGeometryWsl = Convert-WindowsPathToWsl -Path $EyeGeometryDir
    $eyeAppearanceWsl = Convert-WindowsPathToWsl -Path $EyeAppearanceDir
    $bridgeWsl = Convert-WindowsPathToWsl -Path $bridgeScript
    $reviewVrmPath = Join-Path $partial "source-eye-review.vrm"
    $bridgeResultPath = Join-Path $partial "source-eye-review-bridge.json"
    $reviewVrmWsl = Convert-WindowsPathToWsl -Path $reviewVrmPath
    $bridgeResultWsl = Convert-WindowsPathToWsl -Path $bridgeResultPath

    Write-Host "BodyRig eye-only review runtime rebuild"
    Write-Host "Revision:           $head"
    Write-Host "Package SHA:        $(Sha256 $PackagePath)"
    Write-Host "Source fingerprint: $($prepared.source_fingerprint_sha256)"
    Write-Host "Bridge SHA:         $bridgeScriptSha"
    Write-Host "Hair runtime:       FORBIDDEN"
    Write-Host "Package mutation:   FALSE"
    Write-Host "Production:         FALSE"
    Write-Host ""

    $run = Invoke-WslRaw -Arguments @(
        $venvPython, $bridgeWsl,
        "--avatar-vrm", $avatarWsl,
        "--candidate-workspace", $workspaceWsl,
        "--eye-geometry-dir", $eyeGeometryWsl,
        "--eye-appearance-dir", $eyeAppearanceWsl,
        "--smplx-model-dir", $modelDir,
        "--smplx-uv-obj", $uvObj,
        "--output-vrm", $reviewVrmWsl,
        "--output-result", $bridgeResultWsl
    )
    foreach ($line in $run.Lines) { Write-Host ([string]$line) }
    if ($run.ExitCode -ne 0) { throw "Eye-only review bridge failed with exit code $($run.ExitCode)." }
    Need-File -Path $reviewVrmPath -Label "Rebuilt eye-only review VRM" | Out-Null
    Need-File -Path $bridgeResultPath -Label "Eye-only bridge result" | Out-Null

    $finalRaw = Invoke-BodyRigPython -Python $python -RepoRoot $repoRoot -Label "Finalize eye-only runtime rebuild" -Arguments @(
        "-m", "bodyrig.high_fidelity_eye_runtime_rebuild_cli", "finalize",
        "--preview-job-id", $PreviewJobId,
        "--package", $PackagePath,
        "--base-runtime-dir", $BaseRuntimeDir,
        "--iris-candidate-dir", $IrisCandidateDir,
        "--source-eye-appearance-dir", $EyeAppearanceDir,
        "--reviewed-runtime-dir", $ReviewedRuntimeDir,
        "--staging-dir", $partial,
        "--bodyrig-revision", $head,
        "--bridge-script-sha256", $bridgeScriptSha
    )
    try { $final = $finalRaw | ConvertFrom-Json -Depth 30 }
    catch { throw "Eye-only rebuild finalize CLI returned unreadable JSON." }
    if ($final.ok -ne $true -or [string]$final.mode -ne "finalize" -or [string]$final.bodyrig_revision -ne $head) {
        throw "Eye-only rebuild finalizer did not bind the exact checkout."
    }
    if ($final.fingerprint_match -ne $true -or [string]$final.source_fingerprint_sha256 -ne [string]$final.rebuilt_fingerprint_sha256) {
        throw "Eye-only rebuild does not match the exact reviewed semantic fingerprint."
    }
    if ($final.source_hair_runtime_imported -ne $false -or $final.eye_only_runtime_verified -ne $true -or
        $final.eye_component_authority -ne $false -or $final.package_mutation_performed -ne $false -or
        $final.eyes_promoted -ne $false -or $final.production_activation -ne $false) {
        throw "Eye-only rebuild crossed hair/component/package/production authority."
    }
    $receiptPath = Need-File -Path ([string]$final.rebuild_receipt_path) -Label "Eye-only rebuild receipt"

    Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head | Out-Null
    if ((Sha256 $bridgeScript) -ne $bridgeScriptSha) { throw "Eye-only bridge bytes changed during rebuild." }
    if (Test-Path -LiteralPath $OutputDir) { throw "Eye-only rebuild output appeared during build: $OutputDir" }
    Move-Item -LiteralPath $partial -Destination $OutputDir
    $committed = $true

    Write-Host ""
    Write-Host "BodyRig eye-only runtime rebuild: FINGERPRINT MATCH"
    Write-Host "Output:             $OutputDir"
    Write-Host "Review VRM:         $(Join-Path $OutputDir 'source-eye-review.vrm')"
    Write-Host "Source fingerprint: $($final.source_fingerprint_sha256)"
    Write-Host "Rebuilt fingerprint:$($final.rebuilt_fingerprint_sha256)"
    Write-Host "Hair imported:      FALSE"
    Write-Host "Eye authority:      FALSE"
    Write-Host "Package mutated:    FALSE"
    Write-Host "Eyes promoted:      FALSE"
    Write-Host "Production:         FALSE"
    Write-Host "NEXT: a separate package materializer may consume only this fingerprint-matched eye-only runtime."
    exit 0
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $partial)) {
        Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue
    }
}
