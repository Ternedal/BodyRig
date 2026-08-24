param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$SithInstallRoot = "",
    [string]$OpenPoseRepo = "",
    [string]$OpenPoseExecutable = "",
    [string]$DiffusionModel = "",
    [string]$SmplxSource = "",
    [string]$ReportPath = "",
    [string]$BodyRigPython = "",
    [string]$WslExe = "wsl.exe",
    [switch]$ProvisionOpenPose,
    [switch]$DownloadPublicCheckpoints,
    [switch]$SkipDependencyInstall,
    [switch]$PersistUserEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SithRevision = "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d"
$OpenPoseRevision = "8ca5c1d95a42340b323e9273654d1db98bec779c"

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-WindowsFile {
    param([string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    if (-not (Test-Path -LiteralPath $Value -PathType Leaf)) { throw "$Label not found: $Value" }
    return (Resolve-Path -LiteralPath $Value).Path
}

function Invoke-BodyRigChecked {
    param([Parameter(Mandatory = $true)][object[]]$Arguments, [Parameter(Mandatory = $true)][string]$Step)
    & $BodyRigPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$WslExe = $(
    if (Test-Path -LiteralPath $WslExe -PathType Leaf) { (Resolve-Path -LiteralPath $WslExe).Path }
    else {
        $resolved = Resolve-CommandPath $WslExe
        if ($null -eq $resolved) { throw "WSL executable not found: $WslExe" }
        $resolved
    }
)
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }

$homeRaw = & $WslExe -d $Distribution -- /usr/bin/python3 -c "import pathlib; print(pathlib.Path.home().as_posix())" 2>&1
if ($LASTEXITCODE -ne 0) { throw "Could not resolve WSL home in distribution $Distribution." }
$linuxHome = (@($homeRaw) -join "`n").Trim()
if ([string]::IsNullOrWhiteSpace($linuxHome) -or -not $linuxHome.StartsWith("/")) { throw "WSL home probe returned an invalid path." }

if ([string]::IsNullOrWhiteSpace($SithInstallRoot)) { $SithInstallRoot = "$linuxHome/.local/share/bodyrig/sith" }
if (-not $SithInstallRoot.StartsWith("/")) { throw "-SithInstallRoot must be an absolute Linux path." }
$SithInstallRoot = $SithInstallRoot.TrimEnd("/")
$SithPython = "$SithInstallRoot/.bodyrig-venv/bin/python"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) { $BodyRigPython = $venv }
    else { $BodyRigPython = Resolve-CommandPath "python" }
}
$BodyRigPython = Resolve-WindowsFile -Value $BodyRigPython -Label "BodyRig Python"

if ([string]::IsNullOrWhiteSpace($DiffusionModel)) {
    $DiffusionModel = [string][Environment]::GetEnvironmentVariable("BODYRIG_SITH_DIFFUSION_MODEL")
}
if ([string]::IsNullOrWhiteSpace($DiffusionModel) -or -not $DiffusionModel.StartsWith("/")) {
    throw "A local absolute Linux diffusion model path is required via -DiffusionModel or BODYRIG_SITH_DIFFUSION_MODEL."
}

if ([string]::IsNullOrWhiteSpace($OpenPoseRepo)) {
    $OpenPoseRepo = [string][Environment]::GetEnvironmentVariable("BODYRIG_SITH_OPENPOSE_REPO")
}
if ([string]::IsNullOrWhiteSpace($OpenPoseExecutable)) {
    $OpenPoseExecutable = [string][Environment]::GetEnvironmentVariable("BODYRIG_SITH_OPENPOSE")
}

if ($ProvisionOpenPose) {
    if ([string]::IsNullOrWhiteSpace($OpenPoseRepo)) { $OpenPoseRepo = "$linuxHome/.local/share/bodyrig/openpose-v1.7.0" }
    if (-not $OpenPoseRepo.StartsWith("/")) { throw "-OpenPoseRepo must be an absolute Linux path." }
    $openPoseSetup = Join-Path $repoRoot "setup-openpose-wsl.ps1"
    if (-not (Test-Path -LiteralPath $openPoseSetup -PathType Leaf)) { throw "setup-openpose-wsl.ps1 not found." }
    & $openPoseSetup -Distribution $Distribution -InstallRoot $OpenPoseRepo -WslExe $WslExe
    if ($LASTEXITCODE -ne 0) { throw "Pinned OpenPose provisioning failed with exit code $LASTEXITCODE" }
    $OpenPoseExecutable = "$($OpenPoseRepo.TrimEnd('/'))/build/examples/openpose/openpose.bin"
}

if ([string]::IsNullOrWhiteSpace($OpenPoseRepo) -or -not $OpenPoseRepo.StartsWith("/")) {
    throw "Pinned OpenPose repository is required via -OpenPoseRepo, BODYRIG_SITH_OPENPOSE_REPO, or -ProvisionOpenPose."
}
$OpenPoseRepo = $OpenPoseRepo.TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($OpenPoseExecutable)) {
    $OpenPoseExecutable = "$OpenPoseRepo/build/examples/openpose/openpose.bin"
}
if (-not $OpenPoseExecutable.StartsWith("/")) { throw "OpenPose executable must be an absolute Linux path." }

$setupSith = Join-Path $repoRoot "setup-sith-wsl.ps1"
if (-not (Test-Path -LiteralPath $setupSith -PathType Leaf)) { throw "setup-sith-wsl.ps1 not found." }
$setupArgs = @{
    Distribution = $Distribution
    InstallRoot = $SithInstallRoot
    OpenPose = $OpenPoseExecutable
    DiffusionModel = $DiffusionModel
    BodyRigPython = $BodyRigPython
    WslExe = $WslExe
}
if (-not [string]::IsNullOrWhiteSpace($SmplxSource)) { $setupArgs.SmplxSource = $SmplxSource }
if ($DownloadPublicCheckpoints) { $setupArgs.DownloadPublicCheckpoints = $true }
if ($SkipDependencyInstall) { $setupArgs.SkipDependencyInstall = $true }
& $setupSith @setupArgs
if ($LASTEXITCODE -ne 0) { throw "Pinned SiTH provisioning failed with exit code $LASTEXITCODE" }

$preflightArgs = @(
    "-m", "bodyrig.sith_preflight",
    "--distribution", $Distribution,
    "--repo", $SithInstallRoot,
    "--python", $SithPython,
    "--openpose", $OpenPoseExecutable,
    "--openpose-repo", $OpenPoseRepo,
    "--wsl-exe", $WslExe
)
Invoke-BodyRigChecked -Arguments $preflightArgs -Step "Pinned SiTH/OpenPose authority preflight"

$digestArgs = @(
    "-m", "bodyrig.sith_model",
    "--distribution", $Distribution,
    "--python", $SithPython,
    "--model-path", $DiffusionModel,
    "--wsl-exe", $WslExe
)
$digestRaw = & $BodyRigPython @digestArgs
if ($LASTEXITCODE -ne 0) { throw "SiTH diffusion model digest failed." }
try { $digest = $digestRaw | ConvertFrom-Json }
catch { throw "SiTH diffusion model digest returned unreadable JSON." }
if ([string]$digest.sha256 -notmatch '^[0-9a-f]{64}$') { throw "SiTH diffusion model digest is invalid." }
if ([int64]$digest.file_count -lt 1 -or [int64]$digest.byte_count -lt 1) { throw "SiTH diffusion model digest counts are invalid." }

if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $base = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = [System.IO.Path]::GetTempPath() }
    $ReportPath = Join-Path $base "BodyRig\sith\setup-report.json"
}
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)
$reportParent = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Path $reportParent -Force | Out-Null
$tempReport = "$ReportPath.tmp-$([Guid]::NewGuid().ToString('N'))"
$report = [ordered]@{
    format = "bodyrig-sith-setup"
    version = 1
    distribution = $Distribution
    sith = [ordered]@{
        repository = $SithInstallRoot
        revision = $SithRevision
        python = $SithPython
    }
    openpose = [ordered]@{
        repository = $OpenPoseRepo
        revision = $OpenPoseRevision
        executable = $OpenPoseExecutable
    }
    diffusion_model = [ordered]@{
        path = $DiffusionModel
        sha256 = ([string]$digest.sha256).ToLowerInvariant()
        file_count = [int64]$digest.file_count
        byte_count = [int64]$digest.byte_count
    }
}
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($tempReport, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Invoke-BodyRigChecked -Arguments @("-m", "bodyrig.sith_setup", $tempReport) -Step "Validate SiTH setup report"
Move-Item -LiteralPath $tempReport -Destination $ReportPath -Force

$settings = [ordered]@{
    BODYRIG_SITH_SETUP_REPORT = $ReportPath
    BODYRIG_SITH_DISTRIBUTION = $Distribution
    BODYRIG_SITH_REPO = $SithInstallRoot
    BODYRIG_SITH_PYTHON = $SithPython
    BODYRIG_SITH_OPENPOSE_REPO = $OpenPoseRepo
    BODYRIG_SITH_OPENPOSE = $OpenPoseExecutable
    BODYRIG_SITH_DIFFUSION_MODEL = $DiffusionModel
    BODYRIG_SITH_DIFFUSION_SHA256 = ([string]$digest.sha256).ToLowerInvariant()
}
foreach ($entry in $settings.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Key)" -Value ([string]$entry.Value)
    if ($PersistUserEnvironment) {
        [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value, "User")
    }
}

Write-Host ""
Write-Host "BodyRig high-fidelity WSL setup: PASS"
Write-Host "SiTH revision: $SithRevision"
Write-Host "OpenPose revision: $OpenPoseRevision"
Write-Host "Setup report: $ReportPath"
Write-Host "Diffusion model SHA-256: $([string]$digest.sha256)"
if ($PersistUserEnvironment) { Write-Host "BODYRIG_SITH_* settings persisted to the current Windows user." }
else { Write-Host "BODYRIG_SITH_* settings exported for this PowerShell process only." }
exit 0
