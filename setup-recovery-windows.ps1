param(
    [string]$Root = "",
    [string]$CondaExe = "",
    [string]$SmplModelPath = "",
    [switch]$RecreateEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FourDRevision = "efe18deff163b29dff87ddbd575fa29b716a356c"
$PhalpRevision = "96f7e6c09fb858ec3f597d59246c151ab4394bc3"
$FourDRemote = "https://github.com/shubham-goel/4D-Humans.git"
$PhalpRemote = "https://github.com/brjathu/PHALP.git"
$SmplFileName = "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Step,
        [string]$WorkingDirectory = ""
    )
    if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        & $Executable @Arguments
    } else {
        Push-Location $WorkingDirectory
        try { & $Executable @Arguments } finally { Pop-Location }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Assert-ManagedRepo {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Remote,
        [Parameter(Mandatory = $true)][string]$Revision,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $created = $false
    if (-not (Test-Path -LiteralPath $Path)) {
        Invoke-Checked -Executable $script:GitExe -Arguments @("clone", "--no-checkout", $Remote, $Path) -Step "Clone $Label"
        $created = $true
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Path ".git") -PathType Container)) {
        throw "$Label path exists but is not a Git checkout: $Path"
    }

    $actualRemote = (& $script:GitExe -C $Path remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not read $Label origin remote." }
    $normalizedActual = $actualRemote.TrimEnd("/").ToLowerInvariant()
    $normalizedExpected = $Remote.TrimEnd("/").ToLowerInvariant()
    if ($normalizedActual -ne $normalizedExpected) {
        throw "$Label origin mismatch: $actualRemote"
    }

    # Existing managed checkouts remain fail-closed. A repository created by
    # this invocation was cloned with --no-checkout, so Git reports the empty
    # worktree as deleted tracked files until the first checkout. Do not
    # misclassify that expected initial state as operator modifications.
    if (-not $created) {
        $dirty = @(& $script:GitExe -C $Path status --porcelain)
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect $Label status." }
        if ($dirty.Count -gt 0) {
            throw "$Label checkout is dirty. BodyRig will not reset or overwrite it automatically: $Path"
        }
    }

    Invoke-Checked -Executable $script:GitExe -Arguments @("-C", $Path, "fetch", "--no-tags", "origin", $Revision) -Step "Fetch pinned $Label revision"
    Invoke-Checked -Executable $script:GitExe -Arguments @("-C", $Path, "checkout", "--detach", $Revision) -Step "Checkout pinned $Label revision"
    $head = (& $script:GitExe -C $Path rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $head -ne $Revision) {
        throw "$Label checkout did not land on pinned revision $Revision"
    }

    $dirtyAfterCheckout = @(& $script:GitExe -C $Path status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect $Label status after pinned checkout." }
    if ($dirtyAfterCheckout.Count -gt 0) {
        throw "$Label checkout is dirty after pinned checkout: $Path"
    }
}

$script:GitExe = Resolve-CommandPath "git"
if ($null -eq $script:GitExe) {
    throw "Git is required. Install Git for Windows and rerun."
}

if ([string]::IsNullOrWhiteSpace($CondaExe)) {
    foreach ($candidate in @("conda", "mamba")) {
        $resolved = Resolve-CommandPath $candidate
        if ($null -ne $resolved) {
            $CondaExe = $resolved
            break
        }
    }
}
if ([string]::IsNullOrWhiteSpace($CondaExe) -or -not (Test-Path -LiteralPath $CondaExe -PathType Leaf)) {
    throw "Conda/Mamba was not found. Upstream 4D-Humans recommends a Python 3.10 conda environment; install Miniconda/Conda first or pass -CondaExe."
}
$CondaExe = (Resolve-Path -LiteralPath $CondaExe).Path

if ([string]::IsNullOrWhiteSpace($Root)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable; pass -Root explicitly."
    }
    $Root = Join-Path $env:LOCALAPPDATA "BodyRig\recovery"
}
$Root = [System.IO.Path]::GetFullPath($Root)
New-Item -ItemType Directory -Force -Path $Root | Out-Null

$fourDPath = Join-Path $Root "4D-Humans"
$phalpPath = Join-Path $Root "PHALP"
$envPath = Join-Path $Root "conda-env"

Write-Host "BodyRig recovery provisioner"
Write-Host "Root: $Root"
Write-Host "4D-Humans pin: $FourDRevision"
Write-Host "PHALP pin:      $PhalpRevision"

Assert-ManagedRepo -Path $fourDPath -Remote $FourDRemote -Revision $FourDRevision -Label "4D-Humans"
Assert-ManagedRepo -Path $phalpPath -Remote $PhalpRemote -Revision $PhalpRevision -Label "PHALP"

if ($RecreateEnvironment -and (Test-Path -LiteralPath $envPath)) {
    Write-Host "Removing managed recovery environment because -RecreateEnvironment was supplied."
    Invoke-Checked -Executable $CondaExe -Arguments @("env", "remove", "--prefix", $envPath, "--yes") -Step "Remove recovery conda environment"
}

$envPython = Join-Path $envPath "python.exe"
if (-not (Test-Path -LiteralPath $envPython -PathType Leaf)) {
    # The pinned 4D-Humans environment.yml mixes Conda packages with pip VCS
    # packages. Modern pip builds Detectron2 in an isolated PEP 517 environment,
    # where its setup.py cannot import the Torch that Conda just installed. Build
    # the immutable Conda portion explicitly first, then install the pinned local
    # checkouts below with build isolation disabled. --override-channels also
    # prevents an operator's configured Anaconda defaults from being injected.
    Invoke-Checked -Executable $CondaExe -Arguments @(
        "create",
        "--prefix", $envPath,
        "--yes",
        "--override-channels",
        "--channel", "pytorch",
        "--channel", "nvidia",
        "--channel", "conda-forge",
        "python=3.10",
        "numpy",
        "pytorch",
        "pytorch-cuda=11.8",
        "torchvision",
        "pip"
    ) -Step "Create pinned 4D-Humans Conda base environment"
}
if (-not (Test-Path -LiteralPath $envPython -PathType Leaf)) {
    throw "Recovery Python was not created: $envPython"
}

# Detectron2 imports Torch from setup.py, so source-build dependencies must see
# the already-created runtime environment. Install HMR2 from the verified local
# checkout first. PHALP's setup.py also declares neural-renderer-pytorch, but the
# BodyRig recovery bridge always runs 4D-Humans with render.enable=false and the
# pinned tracker does not import neural_renderer. That legacy CUDA renderer would
# otherwise require a separate native Windows CUDA toolchain for code we never
# execute, so provision the actual tracker/runtime dependencies explicitly and
# install the pinned PHALP checkout with --no-deps.
Invoke-Checked -Executable $envPython -Arguments @(
    "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "-e", $fourDPath
) -Step "Install pinned 4D-Humans checkout"

Invoke-Checked -Executable $envPython -Arguments @(
    "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation",
    "opencv-python",
    "joblib",
    "scikit-learn",
    "pyrender",
    "dill",
    "rich",
    "einops",
    "scenedetect[opencv]",
    "hydra-core",
    "timm",
    "av",
    "smplx==0.1.28",
    "numpy",
    "detectron2 @ git+https://github.com/facebookresearch/detectron2.git",
    "pytube @ git+https://github.com/pytube/pytube.git",
    "pyopengl @ git+https://github.com/mmatl/pyopengl.git",
    "chumpy @ git+https://github.com/mattloper/chumpy"
) -Step "Install BodyRig PHALP runtime dependencies"

Invoke-Checked -Executable $envPython -Arguments @(
    "-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "--no-deps", "-e", $phalpPath
) -Step "Install pinned PHALP checkout"

# These are runtime-neutral helpers present in the pinned upstream environment
# but not declared by the two editable packages. Keep them explicit so the
# provisioned environment remains equivalent to the upstream runtime surface.
Invoke-Checked -Executable $envPython -Arguments @(
    "-m", "pip", "install", "--disable-pip-version-check",
    "hydra-submitit-launcher", "hydra-colorlog", "pyrootutils"
) -Step "Install pinned-environment helper dependencies"

$smplDestination = Join-Path (Join-Path $fourDPath "data") $SmplFileName
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $smplDestination) | Out-Null
if (-not [string]::IsNullOrWhiteSpace($SmplModelPath)) {
    if (-not (Test-Path -LiteralPath $SmplModelPath -PathType Leaf)) {
        throw "SMPL model file not found: $SmplModelPath"
    }
    $sourceSmpl = (Resolve-Path -LiteralPath $SmplModelPath).Path
    if ([System.IO.Path]::GetExtension($sourceSmpl).ToLowerInvariant() -ne ".pkl") {
        throw "SMPL source must be the neutral .pkl model obtained under the SMPL terms."
    }
    Copy-Item -LiteralPath $sourceSmpl -Destination $smplDestination -Force
}

$summary = [ordered]@{
    format = "bodyrig-recovery-environment"
    version = 1
    root = $Root
    external_python = $envPython
    four_d_humans_repo = $fourDPath
    four_d_humans_revision = $FourDRevision
    phalp_repo = $phalpPath
    phalp_revision = $PhalpRevision
    smpl_expected_path = $smplDestination
    smpl_present = (Test-Path -LiteralPath $smplDestination -PathType Leaf)
}
$summaryPath = Join-Path $Root "bodyrig-recovery-environment.json"
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Pinned recovery checkouts/environment prepared."
Write-Host "External Python: $envPython"
Write-Host "4D-Humans repo: $fourDPath"
Write-Host "PHALP repo: $phalpPath"
if (-not $summary.smpl_present) {
    Write-Warning "SMPL neutral model is still missing. BodyRig does not download or redistribute it. Obtain $SmplFileName under the applicable SMPL terms, then rerun with -SmplModelPath <file>."
    Write-Host "Recovery acceptance remains BLOCKED until the SMPL model is present."
    Write-Host "Environment summary: $summaryPath"
    exit 2
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$bodyRigPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $bodyRigPython -PathType Leaf)) {
    $bodyRigPython = Resolve-CommandPath "python"
}
if ($null -eq $bodyRigPython) {
    throw "BodyRig Python not found; cannot run final recovery preflight."
}

$preflightPath = Join-Path $Root "bodyrig-recovery-preflight.json"
Invoke-Checked -Executable $bodyRigPython -Arguments @(
    "-m", "bodyrig.preflight_cli",
    "--python", $envPython,
    "--repo", $fourDPath,
    "--phalp-repo", $phalpPath,
    "--out", $preflightPath
) -Step "BodyRig recovery preflight"

Write-Host "Recovery environment: READY"
Write-Host "Preflight: $preflightPath"
Write-Host "Environment summary: $summaryPath"
Write-Host ""
Write-Host "Next:"
Write-Host ".\run-physical-gate.ps1 -Source <video> -BodyId <id> -Name <name>"
exit 0
