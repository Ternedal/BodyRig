param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$CudaRoot = "/usr/local/cuda-11.7",
    [string]$WslExe = "wsl.exe",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$OpenPoseRevision = "8ca5c1d95a42340b323e9273654d1db98bec779c"
$OpenPoseRemote = "https://github.com/CMU-Perceptual-Computing-Lab/openpose.git"

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
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
$homeProbe = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
if ($homeProbe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($homeProbe.Text)) {
    throw "Ubuntu/WSL Python 3 is required before OpenPose provisioning."
}
$linuxHome = $homeProbe.Text.Trim()
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = "$linuxHome/.local/share/bodyrig/openpose-v1.7.0"
}
if (-not $InstallRoot.StartsWith("/")) {
    throw "-InstallRoot must be an absolute Linux path."
}
$InstallRoot = $InstallRoot.TrimEnd("/")
$executable = "$InstallRoot/build/examples/openpose/openpose.bin"

if ([string]::IsNullOrWhiteSpace($CudaRoot) -or -not $CudaRoot.StartsWith("/")) {
    throw "-CudaRoot must be an absolute Linux path."
}
$CudaRoot = $CudaRoot.TrimEnd("/")
$cudaNvcc = "$CudaRoot/bin/nvcc"
$cudaRuntimeHeader = "$CudaRoot/include/cuda_runtime.h"

Write-Host "BodyRig OpenPose WSL provisioning"
Write-Host "Distribution: $Distribution"
Write-Host "Install root: $InstallRoot"
Write-Host "CUDA root: $CudaRoot"
Write-Host "Pinned OpenPose revision: $OpenPoseRevision"
Write-Host ""

foreach ($command in @("git", "cmake", "make")) {
    $probe = Invoke-WslRaw -Arguments @("/usr/bin/which", $command)
    if ($probe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($probe.Text)) {
        throw "Required WSL build command missing: $command. Install the Ubuntu build dependencies before provisioning OpenPose."
    }
}
if (-not (Test-WslPath -Path $cudaNvcc)) {
    throw "CUDA nvcc is required at the explicit CUDA root: $cudaNvcc"
}
if (-not (Test-WslPath -Path $cudaRuntimeHeader)) {
    throw "CUDA runtime headers are required at the explicit CUDA root: $cudaRuntimeHeader"
}

if (Test-WslPath -Path "$InstallRoot/.git" -Directory) {
    $remote = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "remote", "get-url", "origin") -Step "Read OpenPose origin"
    if ($remote -ne $OpenPoseRemote -and $remote -ne "https://github.com/CMU-Perceptual-Computing-Lab/openpose") {
        throw "Existing OpenPose checkout has unexpected origin: $remote"
    }
    $dirty = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "status", "--porcelain", "--untracked-files=no") -Step "Check OpenPose tracked state"
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "Existing OpenPose checkout has modified tracked files; refusing to provision over it."
    }
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "fetch", "origin", $OpenPoseRevision, "--depth", "1") -Step "Fetch pinned OpenPose revision" | Out-Null
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "checkout", "--detach", $OpenPoseRevision) -Step "Checkout pinned OpenPose revision" | Out-Null
} else {
    $slash = $InstallRoot.LastIndexOf("/")
    $parent = $(if ($slash -gt 0) { $InstallRoot.Substring(0, $slash) } else { "/" })
    Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", $parent) -Step "Create OpenPose install parent" | Out-Null
    Invoke-WslChecked -Arguments @("git", "clone", "--no-checkout", $OpenPoseRemote, $InstallRoot) -Step "Clone OpenPose" | Out-Null
    Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "checkout", "--detach", $OpenPoseRevision) -Step "Checkout pinned OpenPose revision" | Out-Null
}

Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "submodule", "update", "--init", "--recursive") -Step "Initialize OpenPose submodules" | Out-Null
$actualRevision = (Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "rev-parse", "HEAD") -Step "Verify OpenPose revision").ToLowerInvariant()
if ($actualRevision -ne $OpenPoseRevision) {
    throw "Pinned OpenPose revision mismatch after checkout: $actualRevision"
}
$cmakeBlob = (Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "hash-object", "CMakeLists.txt") -Step "Verify OpenPose CMakeLists.txt blob").ToLowerInvariant()
if ($cmakeBlob -ne "2328e66ba9642d324c30bd6fe4d7f9711af7595f") {
    throw "Pinned OpenPose CMakeLists.txt authority mismatch: $cmakeBlob"
}

if (-not $SkipBuild) {
    Invoke-WslChecked -Arguments @(
        "cmake",
        "-S", $InstallRoot,
        "-B", "$InstallRoot/build",
        "-DGPU_MODE=CUDA",
        "-DCUDA_TOOLKIT_ROOT_DIR=$CudaRoot",
        "-DCUDA_NVCC_EXECUTABLE=$cudaNvcc",
        "-DBUILD_EXAMPLES=ON",
        "-DBUILD_PYTHON=OFF",
        "-DDOWNLOAD_BODY_25_MODEL=ON",
        "-DDOWNLOAD_FACE_MODEL=ON",
        "-DDOWNLOAD_HAND_MODEL=ON"
    ) -Step "Configure pinned OpenPose" | Out-Null
    Invoke-WslChecked -Arguments @("cmake", "--build", "$InstallRoot/build", "--parallel") -Step "Build pinned OpenPose" | Out-Null
}

if (-not (Test-WslPath -Path $executable)) {
    throw "Pinned OpenPose executable not found after provisioning: $executable"
}
$dirtyAfter = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "status", "--porcelain", "--untracked-files=no") -Step "Verify final OpenPose tracked state"
if (-not [string]::IsNullOrWhiteSpace($dirtyAfter)) {
    throw "OpenPose tracked files changed during provisioning; refusing authority."
}

Write-Host ""
Write-Host "BodyRig OpenPose provisioning: PASS"
Write-Host "OpenPose repo: $InstallRoot"
Write-Host "OpenPose executable: $executable"
Write-Output (ConvertTo-Json -Compress -InputObject ([ordered]@{
    repository = $InstallRoot
    revision = $OpenPoseRevision
    executable = $executable
}))
exit 0
