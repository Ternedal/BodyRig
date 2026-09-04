param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$OpenPose = "",
    [string]$DiffusionModel = "",
    [string]$SmplxSource = "",
    [string]$BodyRigPython = "",
    [string]$WslExe = "wsl.exe",
    [switch]$DownloadPublicCheckpoints,
    [switch]$SkipDependencyInstall,
    [switch]$PersistUserEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SithRevision = "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d"
$SithRemote = "https://github.com/SiTH-Diffusion/SiTH.git"
$SithCudaRoot = "/usr/local/cuda-12.1"
$NvdiffrastRevision = "253ac4fcea7de5f396371124af597e6cc957bfae"
$SetuptoolsVersion = "80.9.0"
$RuntimeMarkerName = ".bodyrig-sith-runtime-v2"
$CheckpointUrls = [ordered]@{
    "recon_model.pth" = "https://files.ait.ethz.ch/projects/SiTH/recon_model.pth"
    "save_smplerx.pth" = "https://files.ait.ethz.ch/projects/SiTH/save_smplerx.pth"
}
$SmplxFiles = @(
    "SMPLX_NEUTRAL.pkl",
    "SMPLX_NEUTRAL.npz",
    "SMPLX_MALE.pkl",
    "SMPLX_MALE.npz",
    "SMPLX_FEMALE.pkl",
    "SMPLX_FEMALE.npz"
)

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-WindowsFile {
    param([string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    if (-not (Test-Path -LiteralPath $Value -PathType Leaf)) {
        throw "$Label not found: $Value"
    }
    return (Resolve-Path -LiteralPath $Value).Path
}

function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $output = & $WslExe -d $Distribution -- @Arguments 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = @($output)
        Text = (@($output) -join "`n").Trim()
    }
}

function Invoke-WslChecked {
    param(
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    $result = Invoke-WslRaw -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        throw "$Step failed with exit code $($result.ExitCode): $($result.Text)"
    }
    return $result.Text
}

function Invoke-WslStreaming {
    param(
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step
    )
    & $WslExe -d $Distribution -- @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Test-WslPath {
    param([Parameter(Mandatory = $true)][string]$Path, [switch]$Directory, [switch]$Executable)
    $flag = "-f"
    if ($Directory) { $flag = "-d" }
    elseif ($Executable) { $flag = "-x" }
    $result = Invoke-WslRaw -Arguments @("/usr/bin/test", $flag, $Path)
    return $result.ExitCode -eq 0
}

function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)

    # wsl.exe can treat backslashes in direct Linux argv as escape characters.
    # Escape them once before handing the Windows path to wslpath.
    $escapedPath = $Path.Replace('\', '\\')
    return Invoke-WslChecked -Arguments @("wslpath", "-a", "-u", $escapedPath) -Step "WSL path translation"
}

$WslExe = $(
    if (Test-Path -LiteralPath $WslExe -PathType Leaf) {
        (Resolve-Path -LiteralPath $WslExe).Path
    } else {
        $resolved = Resolve-CommandPath $WslExe
        if ($null -eq $resolved) { throw "WSL executable not found: $WslExe" }
        $resolved
    }
)

if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw "WSL distribution is required."
}

$probe = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.Text)) {
    throw "Ubuntu/WSL Python 3 is required before SiTH provisioning."
}
$linuxHome = $probe.Text.Trim()

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = "$linuxHome/.local/share/bodyrig/sith"
}
if (-not $InstallRoot.StartsWith("/")) {
    throw "-InstallRoot must be an absolute Linux path."
}
$InstallRoot = $InstallRoot.TrimEnd("/")
$venvPython = "$InstallRoot/.bodyrig-venv/bin/python"
$runtimeMarker = "$InstallRoot/.bodyrig-venv/$RuntimeMarkerName"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $repoRoot = (Resolve-Path $PSScriptRoot).Path
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        $BodyRigPython = $venv
    } else {
        $BodyRigPython = Resolve-CommandPath "python"
    }
}
$BodyRigPython = Resolve-WindowsFile -Value $BodyRigPython -Label "BodyRig Python"

Write-Host "BodyRig SiTH WSL provisioning"
Write-Host "Distribution: $Distribution"
Write-Host "Install root: $InstallRoot"
Write-Host "Pinned SiTH revision: $SithRevision"
Write-Host "SiTH CUDA toolkit: $SithCudaRoot"
Write-Host ""

if (Test-WslPath -Path "$InstallRoot/.git" -Directory) {
    $remote = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "remote", "get-url", "origin") -Step "Read SiTH origin"
    if ($remote -ne $SithRemote -and $remote -ne "https://github.com/SiTH-Diffusion/SiTH") {
        throw "Existing SiTH checkout has unexpected origin: $remote"
    }
    $dirty = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "status", "--porcelain", "--untracked-files=no") -Step "Check SiTH tracked state"
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "Existing SiTH checkout has modified tracked files; refusing to provision over it."
    }
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "fetch", "origin", $SithRevision, "--depth", "1") -Step "Fetch pinned SiTH revision" | Out-Null
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "checkout", "--detach", $SithRevision) -Step "Checkout pinned SiTH revision" | Out-Null
} else {
    $parent = $InstallRoot.Substring(0, $InstallRoot.LastIndexOf("/"))
    if ([string]::IsNullOrWhiteSpace($parent)) { $parent = "/" }
    Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", $parent) -Step "Create SiTH install parent" | Out-Null
    Invoke-WslChecked -Arguments @("git", "clone", "--no-checkout", $SithRemote, $InstallRoot) -Step "Clone SiTH" | Out-Null
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "checkout", "--detach", $SithRevision) -Step "Checkout pinned SiTH revision" | Out-Null
}

$actualRevision = (Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "rev-parse", "HEAD") -Step "Verify SiTH revision").ToLowerInvariant()
if ($actualRevision -ne $SithRevision) {
    throw "Pinned SiTH revision mismatch after checkout: $actualRevision"
}

if (-not (Test-WslPath -Path $venvPython -Executable)) {
    Invoke-WslChecked -Arguments @("/usr/bin/python3", "-m", "venv", "$InstallRoot/.bodyrig-venv") -Step "Create SiTH Python environment" | Out-Null
}
if (-not (Test-WslPath -Path $venvPython -Executable)) {
    throw "SiTH Python environment was not created: $venvPython"
}

if (-not $SkipDependencyInstall -and -not (Test-WslPath -Path $runtimeMarker)) {
    if (-not (Test-WslPath -Path "$SithCudaRoot/bin/nvcc" -Executable)) {
        throw "SiTH requires CUDA Toolkit 12.1 in WSL at $SithCudaRoot. Keep CUDA 11.7 for OpenPose/recovery and install cuda-toolkit-12-1 side-by-side before rerunning."
    }

    Write-Host "Provisioning/resuming SiTH CUDA 12.1 runtime..."
    Invoke-WslStreaming -Arguments @(
        $venvPython, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
        "pip", "setuptools==$SetuptoolsVersion", "wheel", "ninja"
    ) -Step "Bootstrap SiTH packaging toolchain"

    # SiTH upstream is tested with PyTorch 2.1.0 + CUDA 12.1. Install Torch first
    # so native VCS packages can import torch during their metadata/build stages.
    Invoke-WslStreaming -Arguments @(
        $venvPython, "-m", "pip", "install", "--disable-pip-version-check",
        "torch==2.1.0", "torchvision==0.16.0",
        "--extra-index-url", "https://download.pytorch.org/whl/cu121"
    ) -Step "Install SiTH PyTorch CUDA 12.1 runtime"

    $torchProbe = Invoke-WslChecked -Arguments @(
        $venvPython, "-c",
        "import torch; assert torch.version.cuda == '12.1', torch.version.cuda; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
    ) -Step "Verify SiTH PyTorch CUDA 12.1 runtime"
    Write-Host "SiTH Torch CUDA probe: OK | $torchProbe"

    # Preserve the pinned upstream requirements without modifying the clean SiTH
    # checkout, but install nvdiffrast separately because NVIDIA explicitly
    # requires Torch to be installed and pip build isolation to be disabled.
    $filteredRequirements = "/tmp/bodyrig-sith-requirements-$([Guid]::NewGuid().ToString('N')).txt"
    $filterCode = @'
import pathlib, sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
lines = []
for line in src.read_text(encoding="utf-8").splitlines():
    stripped = line.strip().lower()
    if "github.com/nvlabs/nvdiffrast" in stripped:
        continue
    lines.append(line)
dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
'@
    Invoke-WslChecked -Arguments @("/usr/bin/python3", "-c", $filterCode, "$InstallRoot/requirements.txt", $filteredRequirements) -Step "Stage SiTH requirements without nvdiffrast" | Out-Null
    try {
        Invoke-WslStreaming -Arguments @(
            $venvPython, "-m", "pip", "install", "--disable-pip-version-check", "-r", $filteredRequirements
        ) -Step "Install pinned SiTH Python requirements"
    } finally {
        Invoke-WslRaw -Arguments @("/usr/bin/rm", "-f", $filteredRequirements) | Out-Null
    }

    Invoke-WslStreaming -Arguments @(
        "/usr/bin/env", "CUDA_HOME=$SithCudaRoot", "CUDACXX=$SithCudaRoot/bin/nvcc",
        $venvPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
        "nvdiffrast @ git+https://github.com/NVlabs/nvdiffrast.git@$NvdiffrastRevision"
    ) -Step "Build pinned nvdiffrast against CUDA 12.1"

    Invoke-WslStreaming -Arguments @(
        $venvPython, "-m", "pip", "install", "--disable-pip-version-check", "xatlas"
    ) -Step "Install SiTH UV dependency xatlas"

    $runtimeProbe = Invoke-WslChecked -Arguments @(
        "/usr/bin/env", "CUDA_HOME=$SithCudaRoot",
        $venvPython, "-c",
        "import torch, kaolin, nvdiffrast.torch, cv2, smplx, diffusers, transformers, trimesh, xatlas; assert torch.version.cuda == '12.1'; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
    ) -Step "Verify completed SiTH runtime"
    Write-Host "BodyRig SiTH runtime probe: OK | $runtimeProbe"
    Invoke-WslChecked -Arguments @("/usr/bin/touch", $runtimeMarker) -Step "Publish SiTH runtime completion marker" | Out-Null
} elseif (-not $SkipDependencyInstall) {
    Write-Host "SiTH runtime marker present; reusing completed dependency environment."
}

if ($DownloadPublicCheckpoints) {
    Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", "$InstallRoot/checkpoints") -Step "Create SiTH checkpoint directory" | Out-Null
    foreach ($entry in $CheckpointUrls.GetEnumerator()) {
        $destination = "$InstallRoot/checkpoints/$($entry.Key)"
        if (Test-WslPath -Path $destination) {
            Write-Host "Checkpoint already present; reusing $($entry.Key)"
            continue
        }
        $temporary = "$destination.bodyrig-download"
        Invoke-WslChecked -Arguments @("wget", "--https-only", "--tries=3", "--timeout=30", "-O", $temporary, [string]$entry.Value) -Step "Download $($entry.Key)" | Out-Null
        Invoke-WslChecked -Arguments @("/usr/bin/test", "-s", $temporary) -Step "Validate downloaded $($entry.Key)" | Out-Null
        Invoke-WslChecked -Arguments @("/usr/bin/mv", "-f", $temporary, $destination) -Step "Commit downloaded $($entry.Key)" | Out-Null
    }
}

if (-not [string]::IsNullOrWhiteSpace($SmplxSource)) {
    $sourceLinux = ""
    if (Test-Path -LiteralPath $SmplxSource -PathType Container) {
        $sourceLinux = Convert-WindowsPathToWsl -Path (Resolve-Path -LiteralPath $SmplxSource).Path
    } elseif ($SmplxSource.StartsWith("/")) {
        $sourceLinux = $SmplxSource.TrimEnd("/")
    } else {
        throw "SMPL-X source must be an existing Windows directory or absolute Linux directory."
    }
    Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", "$InstallRoot/data/body_models/smplx") -Step "Create SiTH SMPL-X directory" | Out-Null
    foreach ($leaf in $SmplxFiles) {
        $source = "$sourceLinux/$leaf"
        if (-not (Test-WslPath -Path $source)) {
            throw "Required SMPL-X source asset missing: $source"
        }
        Invoke-WslChecked -Arguments @("/usr/bin/cp", "-f", $source, "$InstallRoot/data/body_models/smplx/$leaf") -Step "Copy $leaf" | Out-Null
    }
}

if ([string]::IsNullOrWhiteSpace($OpenPose)) {
    $OpenPose = [string][Environment]::GetEnvironmentVariable("BODYRIG_SITH_OPENPOSE")
}
if ([string]::IsNullOrWhiteSpace($DiffusionModel)) {
    $DiffusionModel = [string][Environment]::GetEnvironmentVariable("BODYRIG_SITH_DIFFUSION_MODEL")
}
if ([string]::IsNullOrWhiteSpace($OpenPose) -or -not $OpenPose.StartsWith("/")) {
    throw "OpenPose must be supplied as an absolute Linux path via -OpenPose or BODYRIG_SITH_OPENPOSE."
}
if ([string]::IsNullOrWhiteSpace($DiffusionModel) -or -not $DiffusionModel.StartsWith("/")) {
    throw "The local SiTH diffusion model must be supplied as an absolute Linux path via -DiffusionModel or BODYRIG_SITH_DIFFUSION_MODEL."
}

$preflightArgs = @(
    "-m", "bodyrig.sith_preflight",
    "--distribution", $Distribution,
    "--repo", $InstallRoot,
    "--python", $venvPython,
    "--openpose", $OpenPose,
    "--wsl-exe", $WslExe
)
& $BodyRigPython @preflightArgs
if ($LASTEXITCODE -ne 0) {
    throw "SiTH final preflight failed. Resolve the reported local dependency/asset gates before cloning."
}

$reconCheckpoint = "$InstallRoot/checkpoints/recon_model.pth"
$smplerxCheckpoint = "$InstallRoot/checkpoints/save_smplerx.pth"
$reconCheckpointRaw = & $BodyRigPython -m bodyrig.wsl_file_digest --distribution $Distribution --python $venvPython --path $reconCheckpoint --wsl-exe $WslExe
if ($LASTEXITCODE -ne 0) {
    throw "SiTH recon_model checkpoint digest failed."
}
try {
    $reconCheckpointDigest = $reconCheckpointRaw | ConvertFrom-Json
} catch {
    throw "SiTH recon_model checkpoint digest returned unreadable JSON."
}
$reconCheckpointSha = ([string]$reconCheckpointDigest.sha256).ToLowerInvariant()
if ($reconCheckpointSha -notmatch '^[0-9a-f]{64}$' -or [int64]$reconCheckpointDigest.byte_count -lt 1) {
    throw "SiTH recon_model checkpoint digest is invalid."
}

$smplerxCheckpointRaw = & $BodyRigPython -m bodyrig.wsl_file_digest --distribution $Distribution --python $venvPython --path $smplerxCheckpoint --wsl-exe $WslExe
if ($LASTEXITCODE -ne 0) {
    throw "SiTH save_smplerx checkpoint digest failed."
}
try {
    $smplerxCheckpointDigest = $smplerxCheckpointRaw | ConvertFrom-Json
} catch {
    throw "SiTH save_smplerx checkpoint digest returned unreadable JSON."
}
$smplerxCheckpointSha = ([string]$smplerxCheckpointDigest.sha256).ToLowerInvariant()
if ($smplerxCheckpointSha -notmatch '^[0-9a-f]{64}$' -or [int64]$smplerxCheckpointDigest.byte_count -lt 1) {
    throw "SiTH save_smplerx checkpoint digest is invalid."
}

$digestArgs = @(
    "-m", "bodyrig.sith_model",
    "--distribution", $Distribution,
    "--python", $venvPython,
    "--model-path", $DiffusionModel,
    "--wsl-exe", $WslExe
)
$digestRaw = & $BodyRigPython @digestArgs
if ($LASTEXITCODE -ne 0) {
    throw "SiTH diffusion model digest failed."
}
try {
    $digest = $digestRaw | ConvertFrom-Json
} catch {
    throw "SiTH diffusion model digest returned unreadable JSON."
}
$modelSha = [string]$digest.sha256
if ($modelSha -notmatch '^[0-9a-f]{64}$') {
    throw "SiTH diffusion model digest is invalid."
}

$settings = [ordered]@{
    BODYRIG_SITH_DISTRIBUTION = $Distribution
    BODYRIG_SITH_REPO = $InstallRoot
    BODYRIG_SITH_PYTHON = $venvPython
    BODYRIG_SITH_OPENPOSE = $OpenPose
    BODYRIG_SITH_RECON_CHECKPOINT_SHA256 = $reconCheckpointSha
    BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256 = $smplerxCheckpointSha
    BODYRIG_SITH_DIFFUSION_MODEL = $DiffusionModel
    BODYRIG_SITH_DIFFUSION_SHA256 = $modelSha
}
foreach ($entry in $settings.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Key)" -Value ([string]$entry.Value)
    if ($PersistUserEnvironment) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value, "User")
    }
}

Write-Host ""
Write-Host "BodyRig SiTH provisioning: PASS"
Write-Host "SiTH repo: $InstallRoot"
Write-Host "SiTH Python: $venvPython"
Write-Host "OpenPose: $OpenPose"
Write-Host "SiTH recon_model SHA-256: $reconCheckpointSha"
Write-Host "SiTH save_smplerx SHA-256: $smplerxCheckpointSha"
Write-Host "Diffusion model: $DiffusionModel"
Write-Host "Diffusion model SHA-256: $modelSha"
if ($PersistUserEnvironment) {
    Write-Host "BODYRIG_SITH_* settings persisted to the current Windows user."
} else {
    Write-Host "BODYRIG_SITH_* settings exported for this PowerShell process only. Use -PersistUserEnvironment to persist them."
}
exit 0