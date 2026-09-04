param(
    [string]$Root = "",
    [string]$CondaExe = "",
    [string]$SmplModelPath = "",
    [switch]$RecreateEnvironment,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FourDRevision = "efe18deff163b29dff87ddbd575fa29b716a356c"
$PhalpRevision = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
$Detectron2Revision = "a2f4a8771ab77e8411c26b27f24f9489a28a2453"
$ChumpyRevision = "580566eafc9ac68b2614b64d6f7aaa84eebb70da"
$PytubeRevision = "a32fff39058a6f7e5e59ecd06a7467b71197ce35"
$PyOpenGlRevision = "76d1261adee2d3fd99b418e75b0416bb7d2865e6"
$NmrRevision = "e990b3c70f48d39231f607c79d76ce3db4bf7483"
$FourDRemote = "https://github.com/shubham-goel/4D-Humans.git"
$PhalpRemote = "https://github.com/brjathu/PHALP.git"
$NmrRemote = "https://github.com/shubham-goel/NMR.git"
$SmplFileName = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"
$CudaRoot = "/usr/local/cuda-11.7"
$SetuptoolsVersion = "80.9.0"
$RuntimeMarkerName = ".bodyrig-recovery-runtime-v2"

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $output = & $script:WslExe -d $Distribution -- @Arguments 2>&1
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
    & $script:WslExe -d $Distribution -- @Arguments
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
    # Escape them once before handing the Windows path to wslpath; otherwise
    # C:\Users\... may arrive as C:Users... and translation fails.
    $escapedPath = $Path.Replace('\', '\\')
    return Invoke-WslChecked -Arguments @("wslpath", "-a", "-u", $escapedPath) -Step "WSL path translation"
}

function Assert-ManagedRepoWsl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Remote,
        [Parameter(Mandatory = $true)][string]$Revision,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $created = $false
    if (-not (Test-WslPath -Path "$Path/.git" -Directory)) {
        if (Test-WslPath -Path $Path -Directory) {
            throw "$Label path exists in WSL but is not a Git checkout: $Path"
        }
        $parent = $Path.Substring(0, $Path.LastIndexOf("/"))
        Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", $parent) -Step "Create $Label parent" | Out-Null
        Invoke-WslStreaming -Arguments @("git", "clone", "--no-checkout", $Remote, $Path) -Step "Clone $Label"
        $created = $true
    }

    $actualRemote = (Invoke-WslChecked -Arguments @("git", "-C", $Path, "remote", "get-url", "origin") -Step "Read $Label origin").Trim()
    $normalizedActual = $actualRemote.TrimEnd("/").ToLowerInvariant()
    $normalizedExpected = $Remote.TrimEnd("/").ToLowerInvariant()
    if ($normalizedActual -ne $normalizedExpected) {
        throw "$Label origin mismatch in WSL: $actualRemote"
    }

    if (-not $created) {
        $dirty = Invoke-WslChecked -Arguments @("git", "-C", $Path, "status", "--porcelain") -Step "Inspect $Label status"
        if (-not [string]::IsNullOrWhiteSpace($dirty)) {
            throw "$Label checkout is dirty. BodyRig will not reset or overwrite it automatically: $Path"
        }
    }

    Invoke-WslStreaming -Arguments @("git", "-C", $Path, "fetch", "--no-tags", "origin", $Revision) -Step "Fetch pinned $Label revision"
    Invoke-WslStreaming -Arguments @("git", "-C", $Path, "checkout", "--detach", $Revision) -Step "Checkout pinned $Label revision"

    $head = (Invoke-WslChecked -Arguments @("git", "-C", $Path, "rev-parse", "HEAD") -Step "Verify $Label revision").Trim().ToLowerInvariant()
    if ($head -ne $Revision) {
        throw "$Label checkout did not land on pinned revision $Revision"
    }
    $dirtyAfter = Invoke-WslChecked -Arguments @("git", "-C", $Path, "status", "--porcelain", "--untracked-files=no") -Step "Verify $Label tracked state"
    if (-not [string]::IsNullOrWhiteSpace($dirtyAfter)) {
        throw "$Label checkout is dirty after pinned checkout: $Path"
    }
}

$script:WslExe = $(
    if (Test-Path -LiteralPath $WslExe -PathType Leaf) {
        (Resolve-Path -LiteralPath $WslExe).Path
    } else {
        $resolved = Resolve-CommandPath $WslExe
        if ($null -eq $resolved) { throw "WSL executable not found: $WslExe" }
        $resolved
    }
)

if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw "WSL distribution is required for BodyRig recovery."
}

if ([string]::IsNullOrWhiteSpace($Root)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable; pass -Root explicitly."
    }
    $Root = Join-Path $env:LOCALAPPDATA "BodyRig\recovery"
}
$Root = [System.IO.Path]::GetFullPath($Root)
New-Item -ItemType Directory -Force -Path $Root | Out-Null

$homeProbe = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
if ($homeProbe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($homeProbe.Text)) {
    throw "Ubuntu/WSL Python 3 is required before recovery provisioning."
}
$linuxHome = $homeProbe.Text.Trim()
$linuxRoot = "$linuxHome/.local/share/bodyrig/recovery"
$fourDPath = "$linuxRoot/4D-Humans"
$phalpPath = "$linuxRoot/PHALP"
$envPath = "$linuxRoot/venv"
$envPython = "$envPath/bin/python"
$runtimeMarker = "$linuxRoot/$RuntimeMarkerName"

Write-Host "BodyRig recovery provisioner | WSL"
Write-Host "Distribution: $Distribution"
Write-Host "Evidence root: $Root"
Write-Host "Linux root: $linuxRoot"
Write-Host "4D-Humans pin: $FourDRevision"
Write-Host "PHALP pin:      $PhalpRevision"
Write-Host "NMR pin:        $NmrRevision"
Write-Host "CUDA toolkit:   $CudaRoot"
Write-Host ""

if (-not [string]::IsNullOrWhiteSpace($CondaExe)) {
    Write-Host "Note: -CondaExe is retained for CLI compatibility but is not used by WSL recovery."
}

Assert-ManagedRepoWsl -Path $fourDPath -Remote $FourDRemote -Revision $FourDRevision -Label "4D-Humans"
Assert-ManagedRepoWsl -Path $phalpPath -Remote $PhalpRemote -Revision $PhalpRevision -Label "PHALP"

if (-not (Test-WslPath -Path "$CudaRoot/bin/nvcc" -Executable)) {
    throw "BodyRig recovery requires the already-provisioned WSL CUDA 11.7 toolkit: $CudaRoot/bin/nvcc"
}

if ($RecreateEnvironment -and (Test-WslPath -Path $envPath -Directory)) {
    Write-Host "Removing managed WSL recovery environment because -RecreateEnvironment was supplied."
    Invoke-WslChecked -Arguments @("/usr/bin/rm", "-rf", $envPath) -Step "Remove WSL recovery environment" | Out-Null
    Invoke-WslChecked -Arguments @("/usr/bin/rm", "-f", $runtimeMarker) -Step "Remove WSL recovery runtime marker" | Out-Null
}

if (-not (Test-WslPath -Path $envPython -Executable)) {
    Write-Host "Creating WSL Python recovery environment..."
    Invoke-WslStreaming -Arguments @("/usr/bin/python3", "-m", "venv", $envPath) -Step "Create WSL recovery venv"
}

if (-not (Test-WslPath -Path $runtimeMarker)) {
    Write-Host "Provisioning/resuming WSL recovery runtime..."
    Invoke-WslStreaming -Arguments @($envPython, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip", "setuptools==$SetuptoolsVersion", "wheel", "ninja") -Step "Bootstrap WSL recovery pip"
    Invoke-WslStreaming -Arguments @($envPython, "-c", "import pkg_resources; print('BodyRig pkg_resources compatibility: OK')") -Step "Verify WSL setuptools compatibility"

    Invoke-WslStreaming -Arguments @(
        $envPython, "-m", "pip", "install", "--disable-pip-version-check",
        "torch==2.0.1+cu117", "torchvision==0.15.2+cu117",
        "--extra-index-url", "https://download.pytorch.org/whl/cu117"
    ) -Step "Install WSL PyTorch CUDA 11.7 runtime"

    Invoke-WslStreaming -Arguments @(
        $envPython, "-m", "pip", "install", "--disable-pip-version-check",
        "numpy==1.23.5", "pandas==2.0.3", "gdown", "pytorch-lightning==1.9.5", "smplx==0.1.28",
        "pyrender", "opencv-python==4.8.1.78", "yacs", "scikit-image==0.21.0", "einops", "timm==0.9.12",
        "webdataset", "dill", "joblib", "scikit-learn", "rich", "hydra-core==1.3.2", "hydra-submitit-launcher",
        "hydra-colorlog", "pyrootutils", "av", "scenedetect[opencv]"
    ) -Step "Install WSL 4D-Humans runtime dependencies"

    Invoke-WslStreaming -Arguments @(
        $envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
        "chumpy @ git+https://github.com/mattloper/chumpy@$ChumpyRevision",
        "pytube @ git+https://github.com/pytube/pytube.git@$PytubeRevision",
        "pyopengl @ git+https://github.com/mmatl/pyopengl.git@$PyOpenGlRevision"
    ) -Step "Install pinned WSL VCS runtime dependencies"

    Invoke-WslStreaming -Arguments @(
        "/usr/bin/env", "CUDA_HOME=$CudaRoot", "FORCE_CUDA=1",
        $envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
        "detectron2 @ git+https://github.com/facebookresearch/detectron2.git@$Detectron2Revision"
    ) -Step "Build pinned Detectron2 in WSL"

    Invoke-WslStreaming -Arguments @($envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "--no-deps", "-e", $fourDPath) -Step "Install pinned 4D-Humans checkout in WSL"
    Invoke-WslStreaming -Arguments @(
        $envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
        "opencv-python==4.8.1.78", "joblib", "scikit-learn", "pyrender", "dill", "rich", "einops",
        "scenedetect[opencv]", "hydra-core==1.3.2", "timm==0.9.12", "av", "smplx==0.1.28"
    ) -Step "Install BodyRig PHALP runtime dependencies in WSL"
    Invoke-WslStreaming -Arguments @($envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "--no-deps", "-e", $phalpPath) -Step "Install pinned PHALP checkout in WSL"

    Invoke-WslStreaming -Arguments @(
        "/usr/bin/env", "CUDA_HOME=$CudaRoot",
        $envPython, "-c",
        "import torch, detectron2, hmr2, phalp; assert torch.cuda.is_available(); print('BodyRig WSL recovery runtime probe: OK | ' + torch.cuda.get_device_name(0))"
    ) -Step "Verify WSL recovery runtime"

    Invoke-WslChecked -Arguments @("/usr/bin/touch", $runtimeMarker) -Step "Publish WSL recovery runtime marker" | Out-Null
}

if (-not (Test-WslPath -Path $envPython -Executable)) {
    throw "WSL recovery Python was not created: $envPython"
}

# NMR is a real import-time dependency of the pinned 4D-Humans tracker even
# when render.enable=false. Keep it as an incremental authority gate outside
# the v2 base-runtime marker so already-provisioned rigs can self-heal without
# rebuilding the entire recovery environment.
$nmrAuthorityProbe = "import importlib.metadata as m,json,neural_renderer; d=m.distribution('neural-renderer-pytorch'); u=json.loads(d.read_text('direct_url.json') or '{}'); v=u.get('vcs_info') or {}; norm=lambda s:(s or '').lower().rstrip('/').removesuffix('.git'); assert v.get('commit_id') == '$NmrRevision'; assert norm(u.get('url')) == norm('$NmrRemote'); print('BodyRig NMR authority: OK')"
$nmrProbe = Invoke-WslRaw -Arguments @($envPython, "-c", $nmrAuthorityProbe)
if ($nmrProbe.ExitCode -ne 0) {
    Write-Host "Provisioning pinned neural-renderer runtime required by 4D-Humans..."
    Invoke-WslStreaming -Arguments @(
        "/usr/bin/env", "CUDA_HOME=$CudaRoot", "FORCE_CUDA=1", "MAX_JOBS=4",
        $envPython, "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
        "neural-renderer-pytorch @ git+$NmrRemote@$NmrRevision"
    ) -Step "Build pinned neural-renderer in WSL"
}
Invoke-WslStreaming -Arguments @($envPython, "-c", $nmrAuthorityProbe) -Step "Verify pinned neural-renderer authority"

$smplDestination = "$fourDPath/data/$SmplFileName"
Invoke-WslChecked -Arguments @("/usr/bin/mkdir", "-p", "$fourDPath/data") -Step "Create 4D-Humans data directory" | Out-Null
if (-not [string]::IsNullOrWhiteSpace($SmplModelPath)) {
    $sourceSmpl = ""
    if (Test-Path -LiteralPath $SmplModelPath -PathType Leaf) {
        $sourceSmpl = Convert-WindowsPathToWsl -Path (Resolve-Path -LiteralPath $SmplModelPath).Path
    } elseif ($SmplModelPath.StartsWith("/")) {
        $sourceSmpl = $SmplModelPath
    } else {
        throw "SMPL model file not found: $SmplModelPath"
    }
    Invoke-WslChecked -Arguments @("/usr/bin/cp", "-f", $sourceSmpl, $smplDestination) -Step "Copy SMPL neutral model into WSL recovery checkout" | Out-Null
}

$smplPresent = Test-WslPath -Path $smplDestination
$summary = [ordered]@{
    format = "bodyrig-recovery-environment"
    version = 1
    root = $linuxRoot
    external_python = $envPython
    four_d_humans_repo = $fourDPath
    four_d_humans_revision = $FourDRevision
    phalp_repo = $phalpPath
    phalp_revision = $PhalpRevision
    nmr_revision = $NmrRevision
    nmr_remote = $NmrRemote
    smpl_expected_path = $smplDestination
    smpl_present = $smplPresent
}
$summaryPath = Join-Path $Root "bodyrig-recovery-environment.json"
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Pinned WSL recovery checkouts/environment prepared."
Write-Host "External Python: $envPython"
Write-Host "4D-Humans repo: $fourDPath"
Write-Host "PHALP repo: $phalpPath"
Write-Host "NMR revision: $NmrRevision"
if (-not $smplPresent) {
    Write-Warning "SMPL neutral model is still missing. BodyRig does not download or redistribute it."
    Write-Host "Recovery acceptance remains BLOCKED until $SmplFileName is present."
    Write-Host "Environment summary: $summaryPath"
    exit 2
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$bodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $bodyRigPython -PathType Leaf)) {
    $bodyRigPython = Resolve-CommandPath "python"
}
if ($null -eq $bodyRigPython) {
    throw "BodyRig Python not found; cannot run final WSL recovery preflight."
}

$preflightPath = Join-Path $Root "bodyrig-recovery-preflight.json"
& $bodyRigPython -m bodyrig.preflight_cli `
    --python $envPython `
    --repo $fourDPath `
    --phalp-repo $phalpPath `
    --distribution $Distribution `
    --wsl-exe $script:WslExe `
    --out $preflightPath
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig WSL recovery preflight failed. Resolve the reported Linux runtime gate before cloning."
}

Write-Host "Recovery environment: READY | WSL $Distribution"
Write-Host "Preflight: $preflightPath"
Write-Host "Environment summary: $summaryPath"
Write-Host ""
Write-Host "Next: continue the full rig bootstrap; high-fidelity SiTH/OpenPose remains in the same WSL distribution."
exit 0