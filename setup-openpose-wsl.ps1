param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$CudaRoot = "/usr/local/cuda-11.7",
    [string]$ModelBaseUrl = "http://vcl.snu.ac.kr/OpenPose/models/",
    [string]$WslExe = "wsl.exe",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$OpenPoseRevision = "8ca5c1d95a42340b323e9273654d1db98bec779c"
$OpenPoseRemote = "https://github.com/CMU-Perceptual-Computing-Lab/openpose.git"
$CaffeRevision = "1807aadafc934a2a1341021620981cb1ec526b83"
$Pybind11Revision = "085a29436a8c472caaaf7157aa644b571079bcaa"

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)

    # Native tools such as git legitimately write progress/status to stderr even
    # when they exit 0. Keep that output for diagnostics, but make the process
    # exit code the sole success/failure authority for this wrapper.
    $previousErrorActionPreference = $ErrorActionPreference
    $hasNativePreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    $previousNativePreference = $null
    if ($hasNativePreference) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
    }

    try {
        $ErrorActionPreference = "Continue"
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $output = & $WslExe -d $Distribution -- @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }

    $lines = @($output | ForEach-Object { $_.ToString() })
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $lines
        Text = ($lines -join "`n").Trim()
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

function Get-WslMd5 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = Invoke-WslRaw -Arguments @("md5sum", $Path)
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Text)) {
        return $null
    }
    $parts = $result.Text.Trim() -split "\s+", 2
    if ($parts.Count -lt 1) { return $null }
    return $parts[0].ToLowerInvariant()
}

function Assert-WslGitClean {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $status = Invoke-WslChecked -Arguments @("git", "-C", $Repository, "status", "--porcelain", "--untracked-files=no") -Step "Check $Label tracked state"
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "$Label has modified tracked files; refusing authority."
    }
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
$caffeRepo = "$InstallRoot/3rdparty/caffe"
$pybind11Repo = "$InstallRoot/3rdparty/pybind11"

if ([string]::IsNullOrWhiteSpace($CudaRoot) -or -not $CudaRoot.StartsWith("/")) {
    throw "-CudaRoot must be an absolute Linux path."
}
$CudaRoot = $CudaRoot.TrimEnd("/")
$cudaNvcc = "$CudaRoot/bin/nvcc"
$cudaRuntimeHeader = "$CudaRoot/include/cuda_runtime.h"

$modelUri = $null
if (-not [Uri]::TryCreate($ModelBaseUrl, [UriKind]::Absolute, [ref]$modelUri) -or $modelUri.Scheme -notin @("http", "https")) {
    throw "-ModelBaseUrl must be an absolute HTTP(S) URL."
}
$ModelBaseUrl = $ModelBaseUrl.TrimEnd("/") + "/"

Write-Host "BodyRig OpenPose WSL provisioning"
Write-Host "Distribution: $Distribution"
Write-Host "Install root: $InstallRoot"
Write-Host "CUDA root: $CudaRoot"
Write-Host "Model mirror: $ModelBaseUrl"
Write-Host "Pinned OpenPose revision: $OpenPoseRevision"
Write-Host "Pinned CUDA-11 Caffe revision: $CaffeRevision"
Write-Host "cuDNN: disabled (pinned OpenPose CUDA path)"
Write-Host ""

foreach ($command in @("git", "cmake", "make", "wget", "md5sum")) {
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
    $superDirty = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all") -Step "Check OpenPose superproject tracked state"
    if (-not [string]::IsNullOrWhiteSpace($superDirty)) {
        throw "Existing OpenPose checkout has modified tracked superproject files; refusing to provision over it."
    }
    foreach ($submodule in @($caffeRepo, $pybind11Repo)) {
        $probe = Invoke-WslRaw -Arguments @("git", "-C", $submodule, "rev-parse", "--is-inside-work-tree")
        if ($probe.ExitCode -eq 0) {
            Assert-WslGitClean -Repository $submodule -Label "Existing OpenPose submodule $submodule"
        }
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

Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "submodule", "update", "--init", "--recursive", "--force") -Step "Initialize OpenPose submodules" | Out-Null
$actualRevision = (Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "rev-parse", "HEAD") -Step "Verify OpenPose revision").ToLowerInvariant()
if ($actualRevision -ne $OpenPoseRevision) {
    throw "Pinned OpenPose revision mismatch after checkout: $actualRevision"
}
$cmakeBlob = (Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "hash-object", "CMakeLists.txt") -Step "Verify OpenPose CMakeLists.txt blob").ToLowerInvariant()
if ($cmakeBlob -ne "2328e66ba9642d324c30bd6fe4d7f9711af7595f") {
    throw "Pinned OpenPose CMakeLists.txt authority mismatch: $cmakeBlob"
}
$pybind11Head = (Invoke-WslChecked -Arguments @("git", "-C", $pybind11Repo, "rev-parse", "HEAD") -Step "Verify pinned pybind11 revision").ToLowerInvariant()
if ($pybind11Head -ne $Pybind11Revision) {
    throw "Pinned OpenPose pybind11 revision mismatch: $pybind11Head"
}
Assert-WslGitClean -Repository $pybind11Repo -Label "OpenPose pybind11 submodule"

if (-not $SkipBuild) {
    $models = @(
        [pscustomobject]@{ Name = "BODY_25"; RelativePath = "pose/body_25/pose_iter_584000.caffemodel"; Md5 = "78287b57cf85fa89c03f1393d368e5b7" },
        [pscustomobject]@{ Name = "face"; RelativePath = "face/pose_iter_116000.caffemodel"; Md5 = "e747180d728fa4e4418c465828384333" },
        [pscustomobject]@{ Name = "hand"; RelativePath = "hand/pose_iter_102000.caffemodel"; Md5 = "a82cfc3fea7c62f159e11bd3674c1531" }
    )

    foreach ($model in $models) {
        $target = "$InstallRoot/models/$($model.RelativePath)"
        $slash = $target.LastIndexOf("/")
        $targetDir = $target.Substring(0, $slash)
        $existingMd5 = $(if (Test-WslPath -Path $target) { Get-WslMd5 -Path $target } else { $null })
        if ($existingMd5 -ne $model.Md5) {
            Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", $targetDir) -Step "Create $($model.Name) model directory" | Out-Null
            Invoke-WslRaw -Arguments @("/usr/bin/rm", "-f", $target) | Out-Null
            $url = "$ModelBaseUrl$($model.RelativePath)"
            Write-Host "Downloading OpenPose model: $($model.Name)"
            Invoke-WslChecked -Arguments @("wget", "--timeout=30", "--tries=3", "-O", $target, $url) -Step "Download $($model.Name) model" | Out-Null
            $existingMd5 = Get-WslMd5 -Path $target
        }
        if ($existingMd5 -ne $model.Md5) {
            Invoke-WslRaw -Arguments @("/usr/bin/rm", "-f", $target) | Out-Null
            throw "OpenPose $($model.Name) model hash mismatch after download: expected $($model.Md5), got $existingMd5"
        }
        Write-Host "OpenPose model verified: $($model.Name) ($($model.Md5))"
    }

    Invoke-WslChecked -Arguments @(
        "cmake",
        "-S", $InstallRoot,
        "-B", "$InstallRoot/build",
        "-DGPU_MODE=CUDA",
        "-DCUDA_TOOLKIT_ROOT_DIR=$CudaRoot",
        "-DCUDA_NVCC_EXECUTABLE=$cudaNvcc",
        "-DUSE_CUDNN=OFF",
        "-DBUILD_EXAMPLES=ON",
        "-DBUILD_PYTHON=OFF",
        "-DDOWNLOAD_BODY_25_MODEL=OFF",
        "-DDOWNLOAD_FACE_MODEL=OFF",
        "-DDOWNLOAD_HAND_MODEL=OFF"
    ) -Step "Configure pinned OpenPose" | Out-Null
    Invoke-WslChecked -Arguments @("cmake", "--build", "$InstallRoot/build", "--parallel") -Step "Build pinned OpenPose" | Out-Null
}

if (-not (Test-WslPath -Path $executable)) {
    throw "Pinned OpenPose executable not found after provisioning: $executable"
}
$caffeHead = (Invoke-WslChecked -Arguments @("git", "-C", $caffeRepo, "rev-parse", "HEAD") -Step "Verify OpenPose CUDA-11 Caffe revision").ToLowerInvariant()
if ($caffeHead -ne $CaffeRevision) {
    throw "OpenPose CUDA-11 Caffe revision mismatch: expected $CaffeRevision, got $caffeHead"
}
Assert-WslGitClean -Repository $caffeRepo -Label "OpenPose CUDA-11 Caffe submodule"
$pybind11Head = (Invoke-WslChecked -Arguments @("git", "-C", $pybind11Repo, "rev-parse", "HEAD") -Step "Verify final pybind11 revision").ToLowerInvariant()
if ($pybind11Head -ne $Pybind11Revision) {
    throw "OpenPose pybind11 revision mismatch after provisioning: $pybind11Head"
}
Assert-WslGitClean -Repository $pybind11Repo -Label "OpenPose pybind11 submodule"
$dirtyAfter = Invoke-WslChecked -Arguments @("git", "-C", $InstallRoot, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all") -Step "Verify final OpenPose superproject tracked state"
if (-not [string]::IsNullOrWhiteSpace($dirtyAfter)) {
    throw "OpenPose tracked superproject files changed during provisioning; refusing authority."
}

Write-Host ""
Write-Host "BodyRig OpenPose provisioning: PASS"
Write-Host "OpenPose repo: $InstallRoot"
Write-Host "OpenPose executable: $executable"
Write-Host "OpenPose Caffe revision: $CaffeRevision"
Write-Output (ConvertTo-Json -Compress -InputObject ([ordered]@{
    repository = $InstallRoot
    revision = $OpenPoseRevision
    caffe_revision = $CaffeRevision
    executable = $executable
}))
exit 0
