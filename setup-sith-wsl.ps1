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

function Test-WslPath {
    param([Parameter(Mandatory = $true)][string]$Path, [switch]$Directory)
    $flag = $(if ($Directory) { "-d" } else { "-f" })
    $result = Invoke-WslRaw -Arguments @("/usr/bin/test", $flag, $Path)
    return $result.ExitCode -eq 0
}

function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Invoke-WslChecked -Arguments @("wslpath", "-a", $Path) -Step "WSL path translation"
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

if (-not (Test-WslPath -Path $venvPython)) {
    Invoke-WslChecked -Arguments @("/usr/bin/python3", "-m", "venv", "$InstallRoot/.bodyrig-venv") -Step "Create SiTH Python environment" | Out-Null
}
if (-not (Test-WslPath -Path $venvPython)) {
    throw "SiTH Python environment was not created: $venvPython"
}

if (-not $SkipDependencyInstall) {
    Invoke-WslChecked -Arguments @($venvPython, "-m", "pip", "install", "--disable-pip-version-check", "-r", "$InstallRoot/requirements.txt") -Step "Install pinned SiTH requirements" | Out-Null
    Invoke-WslChecked -Arguments @($venvPython, "-m", "pip", "install", "--disable-pip-version-check", "xatlas") -Step "Install SiTH UV dependency xatlas" | Out-Null
}

if ($DownloadPublicCheckpoints) {
    Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", "$InstallRoot/checkpoints") -Step "Create SiTH checkpoint directory" | Out-Null
    foreach ($entry in $CheckpointUrls.GetEnumerator()) {
        $destination = "$InstallRoot/checkpoints/$($entry.Key)"
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
Write-Host "Diffusion model: $DiffusionModel"
Write-Host "Diffusion model SHA-256: $modelSha"
if ($PersistUserEnvironment) {
    Write-Host "BODYRIG_SITH_* settings persisted to the current Windows user."
} else {
    Write-Host "BODYRIG_SITH_* settings exported for this PowerShell process only. Use -PersistUserEnvironment to persist them."
}
exit 0
